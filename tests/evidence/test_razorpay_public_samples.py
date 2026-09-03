"""Evidence layer: untangle vs. Razorpay's OWN published sample recon report.

Most reconciliation demos grade their own homework — you generate the data, so you
generate the answer key, so your "accuracy" only measures your generator. This test
is the antidote: it validates untangle's money model against a file **untangle did
not author**.

`data/razorpay-samples/sample-settlements-recon-report.xlsx` is Razorpay's own
published sample settlement recon report, downloaded verbatim from their docs CDN
(provenance + SHA-256 in `data/razorpay-samples/SOURCES.md`). Razorpay's billing
engine decided the settlement groupings, the per-transaction fees, and the
credit/debit legs. So when untangle's `ReconRow` model and `SettlementIndex`
reproduce the money identity in this file to the paise, that is a property of
*Razorpay's* ledger — external ground truth, not our synthetic benchmark.

No network. No API key. No third-party dependency — the .xlsx is parsed with the
Python standard library (a .xlsx is a zip of XML). Runs fully offline in CI.

Honest scope: this is Razorpay's small illustrative sample (unit-rupee rows), not a
real merchant's production volume. The claim is precisely that untangle **ingests
and conserves Razorpay's own published money legs exactly, including refund-as-debit
sign handling** — not a reconciliation-accuracy claim on a real bank statement.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

import pytest

from engine.models import ReconRow
from engine.reconcile import SettlementIndex

SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "razorpay-samples"
    / "sample-settlements-recon-report.xlsx"
)

_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_letters(ref: str) -> str:
    return "".join(c for c in ref if c.isalpha())


def _read_xlsx(path: Path) -> list[dict[str, str]]:
    """Parse the first worksheet into a list of {column_letter: value} dicts, stdlib only."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            st = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in st.findall("a:si", _NS):
                shared.append(
                    "".join(
                        t.text or ""
                        for t in si.iter(
                            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                        )
                    )
                )
        ws = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows: list[dict[str, str]] = []
        for row in ws.find("a:sheetData", _NS).findall("a:row", _NS):
            cells: dict[str, str] = {}
            for c in row.findall("a:c", _NS):
                v = c.find("a:v", _NS)
                if v is None:
                    continue
                val = shared[int(v.text)] if c.get("t") == "s" else v.text
                cells[_col_letters(c.get("r"))] = val
            rows.append(cells)
    return rows


def _paise(v: str | None) -> int:
    """Rupee string -> exact integer paise. Fails loudly if a value is not whole paise."""
    if v in (None, ""):
        return 0
    scaled = float(v) * 100
    r = round(scaled)
    assert abs(scaled - r) < 1e-6, f"non-integer paise in source: {v!r}"
    return r


def _load_recon_rows() -> list[ReconRow]:
    """Map Razorpay's published recon columns onto untangle's own ReconRow model.

    Razorpay labels its fee column 'fee (exclusive tax)' and itemises 'tax' (18% GST on
    the fee) separately; untangle's convention is tax-inside-fee, so fee_paise = fee + tax
    while tax_paise keeps the GST-on-fee for the recoverable schedule.
    """
    raw = _read_xlsx(SAMPLE)
    header, data = raw[0], raw[1:]
    col = {name: letter for letter, name in header.items()}

    def cell(row: dict[str, str], name: str) -> str | None:
        return row.get(col[name])

    rows: list[ReconRow] = []
    for r in data:
        fee_excl = _paise(cell(r, "fee (exclusive tax)"))
        tax = _paise(cell(r, "tax"))
        rows.append(
            ReconRow(
                entity_id=str(cell(r, "entity_id")),
                type=str(cell(r, "transaction_entity")),
                amount_paise=_paise(cell(r, "amount")),
                fee_paise=fee_excl + tax,  # untangle: tax lives inside fee
                tax_paise=tax,
                debit_paise=_paise(cell(r, "debit")),
                credit_paise=_paise(cell(r, "credit")),
                settlement_id=(str(cell(r, "settlement_id")) or None),
                settlement_utr=(str(cell(r, "settlement_utr")) or None),
                settled_at=None,
                created_at=None,
                on_hold=False,
                dispute_id=None,
                order_id=None,
                method=(cell(r, "payment_method") or None),
                description=None,
            )
        )
    return rows


@pytest.fixture(scope="module")
def recon_rows() -> list[ReconRow]:
    assert SAMPLE.is_file(), f"vendored Razorpay sample missing: {SAMPLE}"
    rows = _load_recon_rows()
    assert rows, "no transaction rows parsed from Razorpay sample"
    return rows


def test_per_row_money_identity_holds(recon_rows: list[ReconRow]) -> None:
    """Razorpay's own per-row identity, reproduced through untangle's ReconRow to the paise.

    payment: credit == amount - fee - tax  and  debit == 0
    refund:  debit  == amount              and  credit == 0
    """
    seen_payment = seen_refund = False
    for row in recon_rows:
        if row.type == "payment":
            seen_payment = True
            assert row.debit_paise == 0, f"{row.entity_id}: payment carried a debit"
            assert row.credit_paise == row.amount_paise - row.fee_paise, (
                f"{row.entity_id}: credit {row.credit_paise} != amount-fee-tax "
                f"{row.amount_paise - row.fee_paise}"
            )
        elif row.type == "refund":
            seen_refund = True
            assert row.credit_paise == 0, f"{row.entity_id}: refund carried a credit"
            assert row.debit_paise == row.amount_paise, (
                f"{row.entity_id}: refund debit {row.debit_paise} != amount {row.amount_paise}"
            )
    assert seen_payment, "sample unexpectedly had no payments"
    assert seen_refund, "sample unexpectedly had no refunds — the refund sign path is the point"


def test_settlement_closure_through_untangle_index(recon_rows: list[ReconRow]) -> None:
    """untangle's SettlementIndex reproduces each settlement's net = Σ(credit - debit), exactly.

    This runs Razorpay's data through untangle's *real* coverage code, not a bespoke sum.
    The settlement containing a refund is the discriminating case: its net is Σ(credit-debit)
    with the refund correctly subtracted, NOT Σ(amount-fee-tax) — the sign trap a naive
    'amount ≈ settlement total' matcher walks straight into.
    """
    index = SettlementIndex(recon_rows)

    independent: dict[str, int] = defaultdict(int)
    for row in recon_rows:
        if row.settlement_id:
            independent[row.settlement_id] += row.credit_paise - row.debit_paise

    assert index.net_by_sid, "SettlementIndex found no settlements"
    for sid, net in index.net_by_sid.items():
        assert net == independent[sid], (
            f"{sid}: untangle net_by_sid {net} != independent Σ(credit-debit) {independent[sid]}"
        )
        assert isinstance(net, int), f"{sid}: settlement net is not exact integer paise"

    # At least one settlement's members include a refund — assert that path is exercised,
    # so the test can never silently degrade into an all-payments (no-sign-trap) check.
    refund_sids = {r.settlement_id for r in recon_rows if r.type == "refund" and r.settlement_id}
    assert refund_sids, "no settlement with a refund leg — refund sign handling went unchecked"
    for sid in refund_sids:
        members = index.rows_by_sid[sid]
        naive_amount_sum = sum(m.amount_paise - m.fee_paise for m in members)
        assert index.net_by_sid[sid] != naive_amount_sum, (
            f"{sid}: refund settlement must differ from the naive amount-sum — sign trap not present"
        )
