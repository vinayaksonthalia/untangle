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

import re
from dataclasses import dataclass

# Code points NOT permitted in XML 1.0 text (control chars other than tab/LF/CR, surrogates, etc.).
_XML_ILLEGAL_RE = re.compile(
    "[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def _xml_escape(s: object) -> str:
    """Escape the 5 XML metacharacters AND drop XML 1.0-forbidden code points (control characters etc.)
    for safe output. A local escaper (not xml.sax.saxutils) so the module imports no `xml` parser — this
    is output-only string escaping, never parsing. Qodo #: uploaded settlement ids/UTRs flow into GUID/
    reference/narration verbatim, so illegal control chars must be stripped or the Tally XML won't parse."""
    text = _XML_ILLEGAL_RE.sub("", str(s))
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&apos;")
    )

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
    from collections import defaultdict

    from engine.covered import resolve_covered_rows_by_id, rows_by_canonical_id

    # Qodo #7: index recon rows as a MULTIMAP so duplicate (type, entity_id) rows are not collapsed to
    # the last one — each covered-key occurrence consumes a distinct row.
    rows_by_key: dict[tuple[str, str], list] = defaultdict(list)
    for r in recon_rows:
        rows_by_key[(r.type, r.entity_id)].append(r)

    entries: list[JournalEntry] = []
    rows_by_id = rows_by_canonical_id(recon_rows)
    for rec in sorted(reconciliations, key=lambda x: x.line_key):
        if rec.covered_row_ids:
            # Strict path: exact, validated rows (fail-closed on identity/duplicate mismatch).
            covered = resolve_covered_rows_by_id(rec, rows_by_id)
        else:
            # Legacy fallback: occurrence-consuming (type, entity_id) so duplicate covered keys
            # still map to distinct rows for pre-row-id reconciliations.
            seen: dict[tuple[str, str], int] = defaultdict(int)
            covered = []
            for k in rec.covered_entity_ids:
                bucket = rows_by_key.get(tuple(k), [])
                if seen[tuple(k)] < len(bucket):
                    covered.append(bucket[seen[tuple(k)]])
                seen[tuple(k)] += 1
        if not covered:
            continue
        # Fees/tax over the covered rows; convention-agnostic MDR (untangle folds GST inside `fee`;
        # a real Razorpay report keeps fee ex-GST and tax separate — detect which).
        fee_sum = sum(r.fee_paise for r in covered)
        itc = sum(r.tax_paise for r in covered)          # the GST amount (an ITC asset) — unambiguous
        mdr_ex_gst = fee_sum - itc if _tax_inside_fee(covered) else fee_sum

        # Qodo #13: derive the clearing (gross) from the covered SETTLEMENT net (not the bank credit),
        # and post the bank-vs-settlement residual (±₹1) EXPLICITLY to a rounding ledger — never hide it
        # in Razorpay Clearing (which would misstate the settlement waterfall).
        covered_net = rec.covered_net_paise
        actual_net = rec.credit_amount_paise             # what actually hit the bank
        drift = actual_net - covered_net                 # the accepted ±₹1 reconciliation residual
        gross = covered_net + mdr_ex_gst + itc           # clearing relieved = settlement gross

        # Qodo #8: identify ALL settlements this voucher clears (a set-sum reconciliation may span
        # several); never keep only the first, and never invent a fallback date.
        sids = sorted({r.settlement_id for r in covered if r.settlement_id}) or [rec.line_key]
        utrs = sorted({r.settlement_utr for r in covered if r.settlement_utr})
        # Voucher date from the earliest real settlement date, falling back to the capture date — never
        # an invented constant (Qodo #8), but a Tally voucher must still carry a date (Qodo #1: don't
        # emit date-less vouchers).
        sdate = min((r.settled_at for r in covered if r.settled_at), default=None)
        if sdate is None:
            sdate = min((r.created_at for r in covered if r.created_at), default=None)
        date = sdate.date().isoformat() if sdate is not None else ""

        lines: list[JournalLine] = [JournalLine(LEDGER_BANK, debit_paise=actual_net)]
        if drift > 0:
            lines.append(JournalLine(LEDGER_ROUNDING, credit_paise=drift))
        elif drift < 0:
            lines.append(JournalLine(LEDGER_ROUNDING, debit_paise=-drift))
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

        settle_lbl = ", ".join(sids) if len(sids) <= 3 else f"{', '.join(sids[:3])} +{len(sids) - 3} more"
        narration = (
            f"Razorpay settlement(s) {settle_lbl} | UTR {', '.join(utrs) or 'n/a'} | gross {_inr(gross)}, "
            f"MDR {_inr(mdr_ex_gst)}, GST-ITC {_inr(itc)}, net {_inr(actual_net)}"
        )
        entry = JournalEntry(
            ref=str(sids[0]), date=date, utr=utrs[0] if utrs else "", narration=narration, lines=tuple(lines)
        )
        # Invariant: never emit an unbalanced voucher.
        assert entry.balanced, (
            f"unbalanced journal entry for {sids[0]}: {entry.total_debit_paise} != {entry.total_credit_paise}"
        )
        entries.append(entry)
    return entries


def to_journal_json(entries: list[JournalEntry]) -> list[dict]:
    return [e.to_dict() for e in entries]


def journal_json_to_tally_xml(journal: list[dict], *, company: str = "Your Company Name") -> str:
    """Serialize the report's journal JSON (as emitted by to_journal_json / report['journal']) to Tally
    XML, so the web layer can offer a download from the report dict alone."""
    entries = [
        JournalEntry(
            ref=str(e.get("ref", "")), date=str(e.get("date", "")), utr=str(e.get("utr", "")),
            narration=str(e.get("narration", "")),
            lines=tuple(
                JournalLine(
                    ln["ledger"],
                    debit_paise=round(float(ln.get("debit_inr", "0") or 0) * 100),
                    credit_paise=round(float(ln.get("credit_inr", "0") or 0) * 100),
                )
                for ln in e.get("lines", [])
            ),
        )
        for e in journal
    ]
    return to_tally_xml(entries, company=company)


def to_tally_xml(entries: list[JournalEntry], *, company: str = "Your Company Name") -> str:
    """A Tally Prime voucher-import file (Gateway of Tally > Import > Vouchers, or HTTP port 9000).
    Sign convention: Debit → ISDEEMEDPOSITIVE Yes + NEGATIVE amount; Credit → No + POSITIVE amount;
    Σ AMOUNT == 0. Dates YYYYMMDD. GUID = deterministic settlement key for idempotency."""
    out: list[str] = [
        "<ENVELOPE>",
        "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>",
        "<BODY><IMPORTDATA>",
        "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>",
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES>",
        "</REQUESTDESC><REQUESTDATA>",
    ]
    for e in entries:
        tdate = e.date.replace("-", "")  # YYYYMMDD; never invent a fallback accounting date (Qodo #8)
        if not tdate:
            continue  # a Tally voucher must carry a real date — skip a date-less entry rather than emit one
        guid = f"UNTANGLE-RZP-{_xml_escape(e.ref)}"
        out.append('<TALLYMESSAGE xmlns:UDF="TallyUDF">')
        out.append('<VOUCHER VCHTYPE="Journal" ACTION="Create" OBJVIEW="Accounting Voucher View">')
        out.append(f"<GUID>{guid}</GUID><REMOTEID>{guid}</REMOTEID>")
        out.append(f"<VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><DATE>{tdate}</DATE><EFFECTIVEDATE>{tdate}</EFFECTIVEDATE>")
        out.append(f"<VOUCHERNUMBER>{guid}</VOUCHERNUMBER><REFERENCE>{_xml_escape(e.utr)}</REFERENCE>")
        out.append(f"<NARRATION>{_xml_escape(e.narration)}</NARRATION>")
        for ln in e.lines:
            if ln.debit_paise:
                amt, pos = -ln.debit_paise / 100, "Yes"
            else:
                amt, pos = ln.credit_paise / 100, "No"
            out.append("<ALLLEDGERENTRIES.LIST>")
            out.append(f"<LEDGERNAME>{_xml_escape(ln.ledger)}</LEDGERNAME>")
            out.append(f"<ISDEEMEDPOSITIVE>{pos}</ISDEEMEDPOSITIVE><AMOUNT>{amt:.2f}</AMOUNT>")
            out.append("</ALLLEDGERENTRIES.LIST>")
        out.append("</VOUCHER></TALLYMESSAGE>")
    out.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return "\n".join(out)
