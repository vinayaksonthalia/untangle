"""
Bank narration templates per rail + UTR mangling (taxonomy B1/B2).

This is deliberately separate, documented text-generation. Real bank
narrations are terse, upper-case, and inconsistent between NEFT/RTGS/IMPS/UPI
and between banks — the whole reason entity resolution over free text is hard.
None of the strings here contain a clean structured field the matcher can
trust blindly; that is the point.
"""

from __future__ import annotations

from typing import Tuple

from .rng import Rng

# ---- Razorpay: references RAZORPAY / RZPX; carries the (maybe mangled) UTR ----
_RZP_TEMPLATES = [
    "NEFT CR-RATN0000088-RAZORPAY SOFTWARE PVT LTD-{utr}",
    "RTGS/{utr}/RAZORPAY SOFTWARE PRIVATE LIM",
    "ACH C/ RAZORPAYX {utr} SETTLEMENT",
    "NEFT-{utr}-RZPX PAYMENTS-MERCHANT SETTLE",
    "IMPS/{utr}/Razorpay/Settlement",
    "NEFT CR-RAZORPAY-{utr}",
]


def mangle_utr(utr: str, rng: Rng) -> str:
    """Truncate / drop chars / uppercase / split with a space — B1."""
    mode = rng.choice(["truncate_tail", "truncate_head", "drop_middle", "upper", "spaced"])
    if mode == "truncate_tail":
        return utr[: max(6, len(utr) - rng.randint(2, 5))]
    if mode == "truncate_head":
        return utr[rng.randint(2, 4):]
    if mode == "drop_middle":
        i = len(utr) // 2
        return utr[: i] + utr[i + rng.randint(1, 3):]
    if mode == "upper":
        return utr.upper()
    # spaced: insert a space partway (banks wrap fields)
    i = rng.randint(4, len(utr) - 3)
    return utr[:i] + " " + utr[i:]


def razorpay_narration(utr: str, rng: Rng) -> str:
    return rng.choice(_RZP_TEMPLATES).format(utr=utr)


# ---- Other payment gateways (Cashfree / PayU / CCAvenue) ----
_OTHER_GW = [
    ("NEFT CR-CASHFREE PAYMENTS INDIA-{ref}", "CF"),
    ("RTGS/PAYU PAYMENTS PVT LTD/{ref}/PAYOUT", "PAYU"),
    ("NEFT-CCAVENUE-INFIBEAM-{ref}-SETTLEMENT", "CCAV"),
    ("ACH C/ EASEBUZZ SETTLEMENT {ref}", "EASE"),
]


def other_gateway_narration(rng: Rng) -> Tuple[str, str]:
    tmpl, tag = rng.choice(_OTHER_GW)
    ref = f"{tag}{rng.digits(12)}"
    return tmpl.format(ref=ref), ref


# ---- Direct UPI collections settled to the account ----
_UPI = [
    "UPI/CR/{ref}/NPCI/COLLECT",
    "UPI SETTLEMENT NPCI {ref}",
    "UPI/{ref}/YESBANK/UPI MERCHANT",
    "BULK UPI CR {ref} NPCI",
]


def direct_upi_narration(rng: Rng) -> Tuple[str, str]:
    ref = rng.digits(12)
    return rng.choice(_UPI).format(ref=ref), ref


# ---- COD remittances (Delhivery / Shiprocket / Shopify) ----
_COD = [
    "NEFT CR-DELHIVERY LTD-COD REMIT-{ref}",
    "RTGS/SHIPROCKET COD PAYOUT/{ref}",
    "NEFT-SHOPIFY COMMERCE-COD-{ref}",
    "NEFT-XPRESSBEES COD SETTLEMENT {ref}",
]


def cod_narration(rng: Rng) -> Tuple[str, str]:
    ref = f"COD{rng.digits(10)}"
    return rng.choice(_COD).format(ref=ref), ref


# ---- Unrelated credits/debits (loans, personal, vendor refund, interest) ----
_UNRELATED_CREDIT = [
    ("RTGS-BAJAJ FINANCE LTD-LOAN DISBURSAL-{ref}", "credit"),
    ("IMPS/{ref}/FROM RAJESH KUMAR/PERSONAL", "credit"),
    ("NEFT REFUND-AMAZON SELLER SERVICES-{ref}", "credit"),
    ("INT.PD:{ref}:SAVINGS INTEREST CREDIT", "credit"),
    ("NEFT CR-GST REFUND-CBIC-{ref}", "credit"),
]


def unrelated_narration(rng_narr: Rng, rng_amt: Rng) -> Tuple[str, str, int, int]:
    tmpl, _ = rng_narr.choice(_UNRELATED_CREDIT)
    ref = rng_narr.digits(10)
    narr = tmpl.format(ref=ref)
    if "LOAN DISBURSAL" in narr:
        credit = rng_amt.randint(5_000_000, 50_000_000)
    elif "INTEREST" in narr:
        credit = rng_amt.randint(1200, 90000)
    elif "PERSONAL" in narr:
        credit = rng_amt.randint(50000, 2_000_000)
    else:
        credit = rng_amt.randint(20000, 1_500_000)
    return narr, ref, credit, 0


def bank_charge_narration(rng: Rng) -> Tuple[str, str]:
    ref = rng.digits(8)
    tmpl = rng.choice([
        "NEFT CHARGES + GST {ref}",
        "RTGS OUTWARD CHG {ref}",
        "ACCOUNT MAINTENANCE CHARGE {ref}",
        "IMPS CHARGES GST {ref}",
    ])
    return tmpl.format(ref=ref), ref
