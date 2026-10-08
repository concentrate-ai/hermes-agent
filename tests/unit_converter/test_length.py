"""Example-based tests for length conversions."""

import pytest

from unit_converter import ConvertError, convert, length


def test_five_km_to_miles_anchor():
    assert length.convert(5, "km", "mi") == pytest.approx(3.106855961, rel=1e-8)


def test_meter_is_base_unit():
    assert length.convert(123.456, "m", "m") == 123.456


def test_exact_defined_factors():
    assert length.convert(1, "km", "m") == 1000.0
    assert length.convert(1, "m", "cm") == 100.0
    assert length.convert(1, "in", "mm") == pytest.approx(25.4, rel=1e-12)
    assert length.convert(1, "mi", "ft") == pytest.approx(5280.0, rel=1e-12)
    assert length.convert(1, "nmi", "m") == 1852.0


def test_facade_dispatches_to_length():
    assert convert(2, "km", "m", category="length") == 2000.0


def test_unknown_unit_raises():
    with pytest.raises(ConvertError, match="unknown unit 'leagues'"):
        length.convert(1, "leagues", "m")


def test_temperature_units_are_rejected_by_factor_path():
    with pytest.raises(ConvertError):
        length.convert(0, "C", "K")
