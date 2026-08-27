"""Money parser: _rupees_to_paise must ROUND (never truncate) and handle signs/commas/edges."""
from __future__ import annotations

import pytest

from engine.ingest import InputError, _rupees_to_paise


def r(s):
    return _rupees_to_paise(s, ctx="test")


def test_basic_and_commas():
    assert r("12345.67") == 1234567
    assert r("1,23,456.78") == 12345678
    assert r("100") == 10000
    assert r("") == 0
    assert r("0.00") == 0


def test_rounds_not_truncates():
    assert r("123456.789") == 12345679          # was 12345678 with truncation
    assert r("100.005") == 10001                # half-up
    assert r("100.994") == 10099
    assert r("0.999") == 100


def test_signs():
    assert r("-50.00") == -5000
    assert r("+50.00") == 5000
    assert r("-.50") == -50
    assert r("-0.01") == -1


def test_invalid_raises():
    for bad in [".", "abc", "1.2.3", "--5", "₹5"]:
        with pytest.raises(InputError):
            r(bad)
