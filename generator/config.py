"""
Central configuration for the `untangle` synthetic-data generator.

DESIGN RULE: every *injection-rate* knob that controls how often a corruption /
commingling / adversarial case fires is a NAMED field on `NoiseRates`, never a
magic number buried in logic. A small, explicitly-enumerated set of STRUCTURAL
constants remains inline where they are arithmetic facts or fixed catalogs
(the GST-on-fee rate, the per-network MDR table, the rounding-drift magnitude
set, and the sample bank-charge amounts); each of those is annotated at its
definition and listed in generator/README.md under "Intentional constants".
The noise taxonomy table in generator/README.md stays in sync with the
`NoiseRates` fields below.

All monetary amounts are in PAISE (integer subunits) — verified against the
Razorpay recon fixture (fixtures/recon_sdk_node_2026-08-21.md), where
payment row amount=100000 means Rs.1000.00.

No wall-clock time and no unseeded randomness ever enters the data logic:
timestamps derive from `base_epoch` and every random draw comes from the
seeded RNG in rng.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# Payment-method mix (Indian enum — verified: fixtures show method ∈
# {card, netbanking, wallet, upi, emi}; card_* fields NULL for non-card).
# Weights are a plausible Indian SMB mix; UPI-dominant.
# ---------------------------------------------------------------------------
METHOD_WEIGHTS: dict[str, float] = {
    "upi": 0.52,
    "card": 0.24,
    "netbanking": 0.12,
    "wallet": 0.08,
    "emi": 0.04,
}

# Card networks / types / issuers observed or plausible. Fixture served
# MasterCard / KARB / credit under the IN variant; a reviewer got AMEX under
# the US variant (V4). We include a realistic Indian spread.
CARD_NETWORKS: list[str] = ["MasterCard", "Visa", "RuPay", "AMEX", "Diners"]
CARD_TYPES: list[str] = ["credit", "debit"]
CARD_ISSUERS: list[str] = ["KARB", "HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PUNB"]
NETBANKING_BANKS: list[str] = ["KKBK", "HDFC", "ICIC", "SBIN", "UTIB", "PUNB", "YESB"]
WALLETS: list[str] = ["paytm", "phonepe", "freecharge", "mobikwik"]

# ---------------------------------------------------------------------------
# Fee model. Verified fact (V4): `tax` is 18% GST ON the fee and is INCLUDED
# WITHIN `fee` (transfer row: debit 100296 = amount 100000 + fee 296, NOT
# +tax). So: base_fee = round(amount * rate); tax = round(base_fee * 0.18);
# fee = base_fee + tax; credit(payment) = amount - fee.
#
# Modal effective *base* rates per cluster. UPI is ~zero-MDR P2M (PROJECT_SPEC
# 4b) — deliberately 0 so the fee-variance detector correctly reports
# "no detectable variance" rather than manufacturing findings.
# ---------------------------------------------------------------------------
GST_ON_FEE_RATE = 0.18

# STRUCTURAL CONSTANT (annotated): per-(network, type) modal base MDR fraction.
# A fixed pricing catalog, not an injection rate. RuPay DEBIT is zero-rated
# (RBI zero-MDR on RuPay debit + BHIM-UPI, effective Jan-2020), so it is
# deliberately 0.0000 — mirroring the UPI zero-MDR treatment below.
MODAL_RATE_CARD: dict[tuple[str, str], float] = {
    # (network, type) -> base MDR fraction
    ("MasterCard", "credit"): 0.0200,
    ("Visa", "credit"): 0.0200,
    ("RuPay", "credit"): 0.0180,
    ("AMEX", "credit"): 0.0350,
    ("Diners", "credit"): 0.0300,
    ("MasterCard", "debit"): 0.0090,
    ("Visa", "debit"): 0.0090,
    ("RuPay", "debit"): 0.0000,  # zero-MDR (RBI RuPay-debit zero-rating)
    ("AMEX", "debit"): 0.0120,
    ("Diners", "debit"): 0.0120,
}
MODAL_RATE_NETBANKING = 0.0090  # ~flat-ish per-bank
MODAL_RATE_WALLET = 0.0180
MODAL_RATE_UPI = 0.0000  # zero-MDR P2M
MODAL_RATE_EMI = 0.0300

# GST slabs on the MERCHANT's goods (order ledger), unrelated to the fee GST.
GST_SLABS: list[float] = [0.05, 0.12, 0.18]

# ---------------------------------------------------------------------------
# Bank-rail commingling mix. Per every `razorpay_per_block` razorpay lines we
# emit this many non-razorpay lines. This makes the statement genuinely
# multi-rail (roughly half the lines are NOT razorpay), which is the whole
# point of the attribution problem (taxonomy B2).
# ---------------------------------------------------------------------------
RAIL_BLOCK_RAZORPAY = 10
RAIL_BLOCK_OTHER_GATEWAY = 3
RAIL_BLOCK_DIRECT_UPI = 4
RAIL_BLOCK_COD = 2
RAIL_BLOCK_UNRELATED = 3


@dataclass
class NoiseRates:
    """
    Every hard case from EXCEPTION_TAXONOMY.md with its injection rate.
    Rates are fractions unless the name says _per_ (then it's a count basis).
    """

    # --- Recon-side / settlement structure ---
    on_hold_rate: float = 0.020          # V7: settled=false, never hits bank this cycle
    dispute_rate: float = 0.015          # V8: payment spawns a chargeback debit later
    refund_rate: float = 0.080           # fraction of settled payments that spawn a refund row
    partial_refund_rate: float = 0.400   # of refunds, fraction that are partial (not full amount)
    cross_cycle_refund_rate: float = 0.35  # V5: refund settles in a LATER batch than its payment
    transfer_rate: float = 0.030         # V2: route transfer rows (trf_*)
    transfer_base_fee_rate: float = 0.0025  # base MDR applied to a route transfer's amount
    adjustment_per_batch: float = 0.35   # V1: expected adjustment rows per settlement batch

    # --- Fee variance (feeds PROJECT_SPEC 4 fee-variance module) ---
    fee_variance_rate: float = 0.030     # row deviates from its cluster modal rate

    # --- Bank-side hard cases ---
    split_settlement_rate: float = 0.080   # V6/B: one settlement -> two bank credits, diff value-dates
    merge_settlement_rate: float = 0.060   # B3: two settlements -> one same-day bank credit
    rounding_drift_rate: float = 0.100     # M4: bank credit differs from true net by a few paise
    mangled_utr_rate: float = 0.300        # B1: UTR in narration truncated/mangled
    mangled_prefix_destroy_share: float = 0.55  # of mangled UTRs, fraction whose epoch prefix is DESTROYED
    utr_absent_rate: float = 0.20          # (of non-mangled rzp lines) UTR echoed NOWHERE (ref_no is a bank txn id)
    bank_charge_per_week: float = 2.0      # B4: NEFT/RTGS charge + GST debit lines per week

    # --- Adversarial hardening (FR-016): defeat single-key baselines ---
    # brand keyword, unique amount, and clean UTR must each FAIL alone.
    brandless_rate: float = 0.22           # rzp settlement lines whose narration carries NO brand token
    amount_collision_rate: float = 0.20    # rzp lines that get a same-amount decoy on another rail
    decoy_brandish_rate: float = 0.18      # non-rzp lines (as a fraction of rzp count) made to look Razorpay-ish
    value_date_jitter_rate: float = 0.60   # rzp lines whose bank value_date is shifted off settled_at (breaks value_date==UTR-epoch)
    carry_forward_rate: float = 0.040      # fraction of settlement batches forced net<=0 (roll forward -> carry_forward)

    # --- Merchant order-ledger corruption (exports from Shopify/Tally/Woo) ---
    order_id_missing_rate: float = 0.040   # M1: order_id blank/empty
    order_id_mangled_rate: float = 0.030   # M1: order_id truncated / case-folded / whitespace
    order_id_duplicate_rate: float = 0.020 # M2: order row duplicated

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Config:
    seed: int = 42
    scale: float = 1.0
    # Fixed base epoch (UTC seconds). Default 2026-06-01 00:00:00 UTC.
    # ALL timestamps are base_epoch + deterministic offsets; no wall clock.
    base_epoch: int = 1_780_272_000
    n_days: int = 30                     # statement window length (days)
    settlements_per_day: int = 4         # razorpay settlement batches per business day
    noise: NoiseRates = field(default_factory=NoiseRates)

    # Derived target: payments scale so that total recon rows comfortably >10k.
    base_payments: int = 11000

    @property
    def n_payments(self) -> int:
        return int(round(self.base_payments * self.scale))

    def summary(self) -> dict:
        return {
            "seed": self.seed,
            "scale": self.scale,
            "base_epoch": self.base_epoch,
            "n_days": self.n_days,
            "settlements_per_day": self.settlements_per_day,
            "target_payments": self.n_payments,
            "method_weights": METHOD_WEIGHTS,
            "noise_rates": self.noise.as_dict(),
        }
