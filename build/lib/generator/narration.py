"""
Bank narration templates per rail + UTR mangling (taxonomy B1/B2).

This is deliberately separate, documented text-generation. Real bank
narrations are terse, upper-case, and inconsistent between NEFT/RTGS/IMPS/UPI
and between banks — the whole reason entity resolution over free text is hard.
None of the strings here contain a clean structured field the matcher can
trust blindly; that is the point.
"""

from __future__ import annotations

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

# Branded, but NO UTR anywhere (bank dropped the reference field). Still a real
# Razorpay settlement; the clean-UTR join finds nothing here.
_RZP_TEMPLATES_NOUTR = [
    "NEFT CR-RAZORPAY SOFTWARE PVT LTD-MERCHANT SETTLEMENT",
    "RTGS/RAZORPAY SOFTWARE PRIVATE LIM/SETTLEMENT",
    "ACH C/ RAZORPAYX SETTLEMENT CREDIT",
]

# BRAND-LESS Razorpay settlements (FR-016 edge case): sponsor-bank IFSC + UTR
# only, the remitter-name field truncated away by the bank. Contains NO
# "RAZORPAY"/"RZPX"/"RZP" token, so a brand grep MISSES these. `{utr}` may be
# absent (None) -> a template without the field is chosen.
_RZP_BRANDLESS_UTR = [
    "NEFT CR-RATN0000088-{utr}",
    "NEFT CR-RATN0000088-MERCHANT SETTLEMENT-{utr}",
    "RTGS/{utr}/RATN0000088",
    "NEFT-{utr}-YESB0PTMUPI-SETTLEMENT",
    "IMPS/{utr}/RATN0000088/SETTLE",
]
_RZP_BRANDLESS_NOUTR = [
    "NEFT CR-RATN0000088-MERCHANT SETTLEMENT",
    "IMPS RATN0000088 SETTLEMENT CREDIT",
    "RTGS/RATN0000088/MERCHANT PAYOUT",
]


def mangle_utr(utr: str, rng: Rng, destroy_prefix: bool = False) -> str:
    """Truncate / drop chars / uppercase / split with a space — B1.

    If `destroy_prefix` is True the 10-digit epoch-like prefix is DESTROYED
    (dropped or replaced), so the UTR can't be reconstructed from its prefix and
    a value_date+amount recovery attack fails (SERIOUS-2). Otherwise the prefix
    is largely preserved (truncate_tail / drop_middle / upper / spaced)."""
    if destroy_prefix:
        suffix = utr[10:] if len(utr) > 10 else utr[len(utr) // 2:]
        mode = rng.choice(["suffix_only", "bankref", "tail_frag"])
        if mode == "suffix_only":
            return suffix.upper()
        if mode == "bankref":
            return "N" + rng.digits(4) + suffix.upper()
        # tail_frag: keep only the last few chars of the whole UTR
        return utr[-rng.randint(4, 6):].upper()
    mode = rng.choice(["truncate_tail", "drop_middle", "upper", "spaced"])
    if mode == "truncate_tail":
        return utr[: max(10, len(utr) - rng.randint(2, 5))]
    if mode == "drop_middle":
        i = len(utr) // 2
        return utr[: i] + utr[i + rng.randint(1, 3):]
    if mode == "upper":
        return utr.upper()
    # spaced: insert a space partway (banks wrap fields)
    i = rng.randint(4, len(utr) - 3)
    return utr[:i] + " " + utr[i:]


def razorpay_narration(utr, rng: Rng) -> str:
    """Branded Razorpay narration. `utr` None -> a UTR-less branded template."""
    if utr is None:
        return rng.choice(_RZP_TEMPLATES_NOUTR)
    return rng.choice(_RZP_TEMPLATES).format(utr=utr)


def razorpay_narration_brandless(utr, rng: Rng) -> str:
    """Brand-less Razorpay narration (no RAZORPAY/RZPX/RZP token)."""
    if utr is None:
        return rng.choice(_RZP_BRANDLESS_NOUTR)
    return rng.choice(_RZP_BRANDLESS_UTR).format(utr=utr)


def bank_txn_ref(rng: Rng) -> str:
    """A bank-assigned transaction reference (NOT the settlement UTR) — used in
    ref_no when the UTR is echoed nowhere, so the clean-UTR join finds nothing."""
    return rng.choice(["N", "S", "R"]) + rng.digits(rng.randint(9, 12))


# ---- Brandish DECOYS: non-Razorpay credits engineered to LOOK Razorpay-ish ----
# They carry a RAZORPAY/RZPX token but are NOT the merchant's settlement (a
# RazorpayX vendor payout, a personal reimbursement, a UPI collect naming a rzp
# handle, a cashback). A brand grep FALSELY attributes these -> precision drops.
_BRANDISH_DECOYS = [
    ("NEFT CR-RAZORPAYX PAYOUTS-VENDOR REFUND-{ref}", "unrelated"),
    ("IMPS/{ref}/FROM RAZORPAY EMPLOYEE WELFARE/REIMB", "unrelated"),
    ("UPI/CR/{ref}/razorpayx@ybl/COLLECT", "direct_upi"),
    ("NEFT-RZPX-{ref}-CASHBACK PROMO", "unrelated"),
    ("RTGS/RAZORPAY CAPITAL LOAN DISBURSAL/{ref}", "unrelated"),
]


def brandish_decoy_narration(rng: Rng):
    """Return (narration, ref, rail) for a Razorpay-looking non-settlement."""
    tmpl, rail = rng.choice(_BRANDISH_DECOYS)
    ref = rng.choice(["RZP", "RX", "N"]) + rng.digits(rng.randint(9, 11))
    return tmpl.format(ref=ref), ref, rail


# ---- Other payment gateways (Cashfree / PayU / CCAvenue) ----
_OTHER_GW = [
    ("NEFT CR-CASHFREE PAYMENTS INDIA-{ref}", "CF"),
    ("RTGS/PAYU PAYMENTS PVT LTD/{ref}/PAYOUT", "PAYU"),
    ("NEFT-CCAVENUE-INFIBEAM-{ref}-SETTLEMENT", "CCAV"),
    ("ACH C/ EASEBUZZ SETTLEMENT {ref}", "EASE"),
]


def other_gateway_narration(rng: Rng) -> tuple[str, str]:
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


def direct_upi_narration(rng: Rng) -> tuple[str, str]:
    ref = rng.digits(12)
    return rng.choice(_UPI).format(ref=ref), ref


# ---- COD remittances (Delhivery / Shiprocket / Shopify) ----
_COD = [
    "NEFT CR-DELHIVERY LTD-COD REMIT-{ref}",
    "RTGS/SHIPROCKET COD PAYOUT/{ref}",
    "NEFT-SHOPIFY COMMERCE-COD-{ref}",
    "NEFT-XPRESSBEES COD SETTLEMENT {ref}",
]


def cod_narration(rng: Rng) -> tuple[str, str]:
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


def unrelated_narration(rng_narr: Rng, rng_amt: Rng) -> tuple[str, str, int, int]:
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


def bank_charge_narration(rng: Rng) -> tuple[str, str]:
    ref = rng.digits(8)
    tmpl = rng.choice([
        "NEFT CHARGES + GST {ref}",
        "RTGS OUTWARD CHG {ref}",
        "ACCOUNT MAINTENANCE CHARGE {ref}",
        "IMPS CHARGES GST {ref}",
    ])
    return tmpl.format(ref=ref), ref
