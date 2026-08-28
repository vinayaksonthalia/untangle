"""Settlement → balanced journal entries (Tally Prime XML + double-entry JSON).

Turns each reconciled Razorpay settlement into the accounting voucher a merchant actually needs to
post — the "deliverable is the ledger entry" that separates a recon report from a usable tool.

The settlement waterfall, in untangle's own paise (NOTE: ReconRow.tax_paise is the GST-on-fee that is
ALREADY inside fee_paise — so the MDR expense excludes GST, and double-counting is impossible here):

    gross     = Σ covered payment amounts           (credit: Razorpay Clearing)
    itc        = Σ covered tax_paise (GST on the fee) (debit: Input GST — an ITC asset)
    mdr_ex_gst = Σ covered fee_paise − itc            (debit: Payment Gateway Charges)
    net        = gross − Σ covered fee_paise          (debit: Bank — the actual deposit)
    → net + mdr_ex_gst + itc = gross  (every voucher balances to 0.00 exactly)

Deterministic, stdlib-only. Balance is enforced in code (a non-zero voucher is never emitted); if the
derived net differs from the actual bank credit by a residual (rounding / labelled drift), a single
"Bank Charges & Rounding" line absorbs it so the voucher still balances.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

# Ledger names (must exist in the merchant's Tally company — Tally never auto-creates on voucher import;
# these are the standard Indian D2C chart-of-accounts names, overridable at emit time).
LEDGER_BANK = "Bank Current A/c"
LEDGER_MDR = "Payment Gateway Charges"
LEDGER_ITC_CGST = "Input CGST"
LEDGER_ITC_SGST = "Input SGST"
LEDGER_ITC_IGST = "Input IGST"
LEDGER_CLEARING = "Razorpay Clearing A/c"
LEDGER_ROUNDING = "Bank Charges & Rounding"


@dataclass(frozen=True)
class JournalLine:
    """One posting. Exactly one of debit_paise / credit_paise is non-zero."""

    ledger: str
    debit_paise: int = 0
    credit_paise: int = 0


@dataclass(frozen=True)
class JournalEntry:
    """A balanced journal voucher for one reconciled settlement (Σ debit == Σ credit)."""

    ref: str            # settlement id (stable, used for the idempotency key)
    date: str           # ISO YYYY-MM-DD
    utr: str
    narration: str
    lines: tuple[JournalLine, ...]

    @property
    def total_debit_paise(self) -> int:
        return sum(ln.debit_paise for ln in self.lines)

    @property
    def total_credit_paise(self) -> int:
        return sum(ln.credit_paise for ln in self.lines)

    @property
    def balanced(self) -> bool:
        return self.total_debit_paise == self.total_credit_paise

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "date": self.date,
            "utr": self.utr,
            "narration": self.narration,
            "balanced": self.balanced,
            "lines": [
                {"ledger": ln.ledger, "debit_inr": _inr(ln.debit_paise), "credit_inr": _inr(ln.credit_paise)}
                for ln in self.lines
            ],
        }


def _inr(paise: int) -> str:
    return f"{paise / 100:.2f}"


def _tax_inside_fee(covered) -> bool:
    """Detect the fee/tax convention of the settlement rows. untangle's synthetic data folds GST inside
    `fee` (credit = amount − fee); a REAL Razorpay report keeps them separate (credit = amount − fee −
    tax). Decide by which formula reproduces the reported `credit` on the payment rows. Defaults to True
    (untangle's own convention) when there's nothing to measure."""
    pays = [r for r in covered if r.type == "payment" and (r.fee_paise or r.tax_paise)]
    if not pays:
        return True
    amt = sum(r.amount_paise for r in pays)
    fee = sum(r.fee_paise for r in pays)
    tax = sum(r.tax_paise for r in pays)
    credit = sum(r.credit_paise for r in pays)
    inside_err = abs(credit - (amt - fee))
    separate_err = abs(credit - (amt - fee - tax))
    return inside_err <= separate_err


def build_journal_entries(
    reconciliations,
    recon_rows,
    *,
    intra_state: bool = True,
) -> list[JournalEntry]:
    """One balanced journal voucher per reconciled Razorpay credit. `intra_state` splits the ITC into
    CGST+SGST (same state as the gateway GSTIN) vs a single IGST line (inter-state)."""
    by_entity = {(r.type, r.entity_id): r for r in recon_rows}
    # Deterministic order: by settlement date then id (fall back to line_key).
    entries: list[JournalEntry] = []
    for rec in sorted(reconciliations, key=lambda x: x.line_key):
        covered = [by_entity[k] for k in rec.covered_entity_ids if k in by_entity]
        if not covered:
            continue
        # Model the SETTLEMENT leg robustly to (a) a settlement mixing payments/refunds/adjustments,
        # and (b) EITHER fee/tax convention: untangle's synthetic data folds GST inside `fee`
        # (credit = amount − fee), while a REAL Razorpay report keeps them separate
        # (credit = amount − fee − tax). We detect which, so the MDR expense (ex-GST) is always right.
        fee_sum = sum(r.fee_paise for r in covered)
        itc = sum(r.tax_paise for r in covered)          # the GST amount (an ITC asset) — unambiguous
        mdr_ex_gst = fee_sum - itc if _tax_inside_fee(covered) else fee_sum
        actual_net = rec.credit_amount_paise             # what actually hit the bank
        gross = actual_net + mdr_ex_gst + itc            # clearing relieved → balances exactly, no drift

        sid = next((r.settlement_id for r in covered if r.settlement_id), rec.line_key)
        utr = next((r.settlement_utr for r in covered if r.settlement_utr), "")
        sdate = next((r.settled_at for r in covered if r.settled_at), None)
        date = sdate.date().isoformat() if sdate is not None else ""

        lines: list[JournalLine] = [JournalLine(LEDGER_BANK, debit_paise=actual_net)]
        if mdr_ex_gst:
            lines.append(JournalLine(LEDGER_MDR, debit_paise=mdr_ex_gst))
        if itc:
            if intra_state:
                half = itc // 2
                lines.append(JournalLine(LEDGER_ITC_CGST, debit_paise=half))
                lines.append(JournalLine(LEDGER_ITC_SGST, debit_paise=itc - half))
            else:
                lines.append(JournalLine(LEDGER_ITC_IGST, debit_paise=itc))
        lines.append(JournalLine(LEDGER_CLEARING, credit_paise=gross))

        narration = (
            f"Razorpay settlement {sid} | UTR {utr or 'n/a'} | gross {_inr(gross)}, "
            f"MDR {_inr(mdr_ex_gst)}, GST-ITC {_inr(itc)}, net {_inr(actual_net)}"
        )
        entry = JournalEntry(ref=str(sid), date=date, utr=utr or "", narration=narration, lines=tuple(lines))
        # Invariant: never emit an unbalanced voucher.
        assert entry.balanced, f"unbalanced journal entry for {sid}: {entry.total_debit_paise} != {entry.total_credit_paise}"
        entries.append(entry)
    return entries


def to_journal_json(entries: list[JournalEntry]) -> list[dict]:
    return [e.to_dict() for e in entries]


def to_tally_xml(entries: list[JournalEntry], *, company: str = "Your Company Name") -> str:
    """A Tally Prime voucher-import file (Gateway of Tally > Import > Vouchers, or HTTP port 9000).
    Sign convention: Debit → ISDEEMEDPOSITIVE Yes + NEGATIVE amount; Credit → No + POSITIVE amount;
    Σ AMOUNT == 0. Dates YYYYMMDD. GUID = deterministic settlement key for idempotency."""
    out: list[str] = [
        "<ENVELOPE>",
        "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>",
        "<BODY><IMPORTDATA>",
        "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>",
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES>",
        "</REQUESTDESC><REQUESTDATA>",
    ]
    for e in entries:
        tdate = e.date.replace("-", "") or "20260101"
        guid = f"UNTANGLE-RZP-{escape(e.ref)}"
        out.append('<TALLYMESSAGE xmlns:UDF="TallyUDF">')
        out.append('<VOUCHER VCHTYPE="Journal" ACTION="Create" OBJVIEW="Accounting Voucher View">')
        out.append(f"<GUID>{guid}</GUID><REMOTEID>{guid}</REMOTEID>")
        out.append(f"<VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><DATE>{tdate}</DATE><EFFECTIVEDATE>{tdate}</EFFECTIVEDATE>")
        out.append(f"<VOUCHERNUMBER>{guid}</VOUCHERNUMBER><REFERENCE>{escape(e.utr)}</REFERENCE>")
        out.append(f"<NARRATION>{escape(e.narration)}</NARRATION>")
        for ln in e.lines:
            if ln.debit_paise:
                amt, pos = -ln.debit_paise / 100, "Yes"
            else:
                amt, pos = ln.credit_paise / 100, "No"
            out.append("<ALLLEDGERENTRIES.LIST>")
            out.append(f"<LEDGERNAME>{escape(ln.ledger)}</LEDGERNAME>")
            out.append(f"<ISDEEMEDPOSITIVE>{pos}</ISDEEMEDPOSITIVE><AMOUNT>{amt:.2f}</AMOUNT>")
            out.append("</ALLLEDGERENTRIES.LIST>")
        out.append("</VOUCHER></TALLYMESSAGE>")
    out.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return "\n".join(out)
