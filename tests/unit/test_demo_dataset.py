"""Regression coverage for the synthetic demo's payment-method evidence."""

from generator.config import Config
from generator.demo_dataset import build_demo_dataset


def test_demo_preserves_payment_methods_in_recon_and_ledger_rows():
    recon, _bank, ledger = build_demo_dataset(Config(seed=7))
    by_order = {row["order_id"]: row["method"] for row in recon if row["order_id"]}
    ledger_methods = {row["order_id"]: row["payment_method"] for row in ledger if row["order_id"]}
    assert {"netbanking", "upi", "card"} <= set(by_order.values())
    assert by_order == ledger_methods
    assert by_order[next(k for k, v in by_order.items() if v == "netbanking")] == "netbanking"
