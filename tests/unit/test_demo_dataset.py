"""Regression coverage for the synthetic demo's payment-method evidence."""

from generator.config import Config
from generator.demo_dataset import _token, build_demo_dataset


def test_demo_preserves_payment_methods_in_recon_and_ledger_rows():
    recon, _bank, ledger = build_demo_dataset(Config(seed=7))
    by_order = {row["order_id"]: row["method"] for row in recon if row["order_id"]}
    ledger_methods = {row["order_id"]: row["payment_method"] for row in ledger if row["order_id"]}
    assert by_order == ledger_methods
    expected_methods = {
        f"order_demo_{_token(7, label + ':order' + str(index))}": method
        for label, method, index in (
            ("netbanking_a", "netbanking", 0),
            ("upi_batch_a", "upi", 0),
            ("card_batch_a", "card", 0),
        )
    }
    for order_id, method in expected_methods.items():
        assert by_order[order_id] == method
        assert ledger_methods[order_id] == method
