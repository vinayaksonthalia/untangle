"""Per-rail evidence signals (data-model.md EvidenceItem, spec FR-003).

Each function returns weighted ``EvidenceItem``s. Nothing here makes a verdict;
``attribute.py`` combines these signals into a rail label or UNKNOWN.

The design follows research R2: no single key is trusted. In particular the
Razorpay brand word is deliberately weak and is voided by decoy markers, because
the benchmark contains non-Razorpay credits engineered to look Razorpay-ish
(``razorpayx@ybl`` VPAs, ``RAZORPAYX PAYOUTS`` vendor refunds). The trustworthy
Razorpay signals are ties back to the recon report: a UTR that matches a
``settlement_utr`` and an amount that matches a settlement net.
"""

from __future__ import annotations

import re
from datetime import date

from engine.models import BankCreditLine, EvidenceItem, Rail, ReconRow

# A Razorpay settlement UTR is 10 digits + 6 lowercase alnum (verified: all 112 in the
# sample recon report match this shape). Anchored on non-alphanumeric boundaries so it does
# NOT slice a 16-char window out of a longer numeric run (e.g. a 20-digit account/reference
# number), which could otherwise manufacture a bogus utr_exact/settlement_ref token. On the
# benchmark this is match-for-match identical to the unanchored form (142 = 142).
_UTR = re.compile(r"(?<![0-9a-z])[0-9]{10}[a-z0-9]{6}(?![0-9a-z])", re.I)
# Generic alphanumeric run, used to test whether a bank token is the SUFFIX of a UTR
# whose prefix the bank destroyed (hard case: prefix_destroyed).
_ALNUM = re.compile(r"[a-z0-9]{5,}", re.I)

# Distinctive brand tokens for the non-Razorpay rails. These are high precision:
# a bank narration carrying "PAYU" is a PayU payout, not a Razorpay settlement.
_RAIL_KEYWORDS: dict[Rail, tuple[str, ...]] = {
    Rail.OTHER_GATEWAY: (
        "payu", "cashfree", "ccavenue", "cc avenue", "easebuzz",
        "billdesk", "instamojo", "infibeam", "phonepe payment",
    ),
    Rail.COD_REMITTANCE: (
        "cod", "shiprocket", "delhivery", "xpressbees", "ecom express",
        "shopify commerce", "cash on delivery",
    ),
    Rail.DIRECT_UPI: (
        "upi settlement", "upi merchant", "upi/cr", "bulk upi cr",
        "npci", "upi/", "@ybl", "@okaxis", "@paytm", "@okhdfcbank",
    ),
    Rail.UNRELATED: (
        "personal", "gst refund", "savings interest", "interest credit",
        "int.pd", "charges", " chg", "outward chg", "vendor refund",
        "payouts", "amazon seller", "salary", "loan disbursal", "cbic",
    ),
}

# Markers that a razorpay-looking token is actually a decoy / different rail.
_DECOY_MARKERS = ("payouts", "vendor refund", "@ybl", "collect", "payout")

# Narration context words that support (but do not prove) a Razorpay settlement.
_RZP_BRAND = ("razorpay", "rzp")
_RZP_CONTEXT = ("settlement", "settle", "razorpay software", "razorpayx settlement")
_RZP_IFSC = "ratn0000088"  # Razorpay's RBL settlement-account IFSC (brand-less tie).

# value-date proximity window to a settlement's settled_at.
_DATE_WINDOW_DAYS = 3


class ReconIndex:
    """Precomputed lookups over the recon report for fast evidence checks."""

    def __init__(self, rows: list[ReconRow]) -> None:
        self.settlement_utrs: set[str] = set()
        self._utr_by_len: dict[int, set[str]] = {}
        self.utr_to_sid: dict[str, str] = {}
        net: dict[str, int] = {}
        sdate: dict[str, date | None] = {}
        for r in rows:
            if r.settlement_utr:
                u = r.settlement_utr.lower()
                self.settlement_utrs.add(u)
                if r.settlement_id:
                    self.utr_to_sid.setdefault(u, r.settlement_id)
            sid = r.settlement_id
            if sid:
                net[sid] = net.get(sid, 0) + r.net_paise
                if r.settled_at is not None:
                    sdate[sid] = r.settled_at.date()
        self.settlement_net = net
        self.settlement_date = sdate
        # amount -> settlement_ids sharing that net
        self.net_to_settlements: dict[int, list[str]] = {}
        for sid, n in net.items():
            self.net_to_settlements.setdefault(n, []).append(sid)
        # sorted distinct positive nets (for bounded set-sum in Tier C)
        self.distinct_nets = sorted({n for n in net.values() if n > 0})

    def utr_exact(self, token: str) -> bool:
        return token.lower() in self.settlement_utrs

    def utr_suffix_match(self, token: str) -> str | None:
        """Return the settlement_utr this token is the suffix of — ONLY if that match is unique.

        A token that is the tail of two or more different settlement_utrs identifies none of them,
        so it is not a usable tie (returns None). Uniqueness is a precondition; the caller further
        requires date/amount corroboration before treating a suffix as a deciding tie.
        """
        t = token.lower()
        if len(t) < 6:
            return None
        matches = [u for u in self.settlement_utrs if u.endswith(t) and u != t]
        return matches[0] if len(matches) == 1 else None


def extract_utr_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _UTR.finditer(text)]


def _has_any(text: str, needles: tuple[str, ...]) -> str | None:
    for n in needles:
        if n in text:
            return n
    return None


def narration_rail_signals(line: BankCreditLine) -> dict[Rail, list[EvidenceItem]]:
    """Distinctive non-Razorpay narration keywords → weighted evidence per rail."""
    text = line.raw_text().lower()
    out: dict[Rail, list[EvidenceItem]] = {}
    for rail, kws in _RAIL_KEYWORDS.items():
        hit = _has_any(text, kws)
        if hit:
            out.setdefault(rail, []).append(
                EvidenceItem(
                    signal=f"narration_pattern:{rail.value}",
                    detail=f"narration contains {hit!r}",
                    weight=0.95,
                )
            )
    return out


def razorpay_signals(line: BankCreditLine, index: ReconIndex) -> list[EvidenceItem]:
    """Evidence that a credit is a Razorpay settlement, tied back to the recon report."""
    ev: list[EvidenceItem] = []
    text = line.raw_text()
    low = text.lower()

    # Tier-A grade: a UTR token that exactly matches a settlement_utr. Zero false
    # positives observed on the benchmark — decoys carry no real settlement UTR.
    tokens = extract_utr_tokens(text)
    matched_exact = next((t for t in tokens if index.utr_exact(t)), None)
    if matched_exact:
        ev.append(EvidenceItem("utr_exact", f"UTR {matched_exact} matches a settlement_utr", 0.95))

    # Destroyed-prefix UTR: a >=6-char token that is the UNIQUE suffix of a real settlement_utr.
    # A suffix is only a DECIDING tie ("utr_suffix") when it uniquely identifies one settlement AND
    # is corroborated against that same settlement by value-date proximity or an exact amount match
    # — otherwise a short (e.g. 6-char) token could coincidentally tail a real UTR and manufacture a
    # false tie. An uncorroborated unique suffix is downgraded to "utr_suffix_weak" (corroboration
    # only; never decides a verdict). (Benchmark: all 12 real suffix cases are unique + corroborated.)
    if not matched_exact:
        # Evaluate ALL suffix candidates deterministically (sorted, not set-iteration order) and
        # prefer a corroborated match over an uncorroborated one, so the emitted signal never
        # depends on hash ordering when a narration contains more than one suffix token.
        strong = None  # (token, utr, how) once a corroborated suffix is found
        weak = None    # (token, utr) — best uncorroborated suffix seen
        for tok in sorted({m.group(0) for m in _ALNUM.finditer(text)}):
            u = index.utr_suffix_match(tok)
            if not u:
                continue
            sid = index.utr_to_sid.get(u)
            sdate = index.settlement_date.get(sid) if sid else None
            snet = index.settlement_net.get(sid) if sid else None
            date_ok = sdate is not None and abs((line.value_date - sdate).days) <= _DATE_WINDOW_DAYS
            amt_ok = line.is_credit and snet is not None and line.amount_paise == snet
            if date_ok or amt_ok:
                strong = (tok, u, "value-date" if date_ok else "amount")
                break  # a corroborated tie is decisive; stop
            if weak is None:
                weak = (tok, u)
        if strong is not None:
            tok, u, how = strong
            ev.append(
                EvidenceItem(
                    "utr_suffix",
                    f"token {tok!r} is the unique suffix of settlement_utr {u}, corroborated by {how}",
                    0.5,
                )
            )
        elif weak is not None:
            tok, u = weak
            ev.append(
                EvidenceItem(
                    "utr_suffix_weak",
                    f"token {tok!r} tails settlement_utr {u} but is uncorroborated (date/amount)",
                    0.2,
                )
            )

    # Amount ties to a settlement net, corroborated by value-date proximity. Only a UNIQUE net
    # match (exactly one settlement has this net) is a deciding tie ("amount_corr"); if several
    # settlements share the net the amount no longer identifies one settlement, so it is emitted
    # as "amount_corr_multi" — corroboration only, never a signal that can decide a razorpay
    # verdict by itself. (On the benchmark every amount match is unique, so this is defensive.)
    if line.is_credit and line.amount_paise in index.net_to_settlements:
        sids = index.net_to_settlements[line.amount_paise]
        near = _date_near(line.value_date, [index.settlement_date.get(s) for s in sids])
        ev.append(
            EvidenceItem(
                "amount_corr" if len(sids) == 1 else "amount_corr_multi",
                f"credit equals settlement net for {len(sids)} settlement(s)"
                + (" within value-date window" if near else ""),
                0.5 if near else 0.3,
            )
        )
        if near:
            ev.append(
                EvidenceItem(
                    "value_date_proximity",
                    f"value_date within {_DATE_WINDOW_DAYS}d of settled_at",
                    0.2,
                )
            )

    # Narration brand/context — weak, and voided when decoy markers are present.
    decoy = _has_any(low, _DECOY_MARKERS)
    if not decoy:
        rzp_identity = _has_any(low, _RZP_BRAND) or (_RZP_IFSC in low)
        if _has_any(low, _RZP_BRAND) and _has_any(low, _RZP_CONTEXT):
            ev.append(EvidenceItem("narration_brand_rzp", "razorpay brand + settlement context", 0.3))
        elif _has_any(low, _RZP_BRAND):
            ev.append(EvidenceItem("narration_brand_rzp", "razorpay brand token (weak)", 0.15))
        if _RZP_IFSC in low:
            ev.append(EvidenceItem("ifsc_ratn", "RATN0000088 (Razorpay RBL settlement IFSC)", 0.25))

        # A UTR-shaped transfer reference alongside a Razorpay identity token, where the
        # UTR is NOT itself a settlement_utr. This is the fingerprint of split-settlement
        # legs (each leg carries its own per-leg bank UTR, absent from the recon report).
        # Gated on a Razorpay identity token so a stray 16-char token elsewhere cannot fire.
        if rzp_identity and tokens and not matched_exact:
            ev.append(
                EvidenceItem(
                    "settlement_ref",
                    "UTR-shaped transfer reference with a Razorpay identity token",
                    0.5,
                )
            )
    return ev


def _date_near(vd: date, candidates: list[date | None]) -> bool:
    for c in candidates:
        if c is not None and abs((vd - c).days) <= _DATE_WINDOW_DAYS:
            return True
    return False


def has_decoy_marker(line: BankCreditLine) -> str | None:
    return _has_any(line.raw_text().lower(), _DECOY_MARKERS)
