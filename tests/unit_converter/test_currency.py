"""Example tests for the currency snapshot.

These assert properties of the static table and its documented anchors —
never correctness of real-world exchange rates.
"""

import pytest

from unit_converter import ConvertError, RATE_SNAPSHOT_DATE, convert, currency


def test_snapshot_date_constant():
    assert RATE_SNAPSHOT_DATE == "2026-10-01"


def test_module_docstring_declares_snapshot():
    assert "snapshot" in (currency.__doc__ or "").lower()
    assert "not live data" in (currency.__doc__ or "").lower()


def test_usd_is_base():
    assert currency.RATES["USD"] == 1.0


def test_hundred_usd_to_eur_anchor():
    assert currency.convert(100, "USD", "EUR") == 92.0


def test_same_currency_is_identity():
    assert currency.convert(42.5, "JPY", "JPY") == 42.5


def test_case_insensitive_codes():
    assert currency.convert(100, "usd", "eur") == 92.0


def test_facade_dispatches_to_currency():
    assert convert(1, "USD", "GBP", category="currency") == pytest.approx(0.79)


def test_unknown_currency_raises():
    with pytest.raises(ConvertError, match="unknown currency 'BTC'"):
        currency.convert(1, "BTC", "USD")
