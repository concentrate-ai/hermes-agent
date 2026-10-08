"""Example-based tests for affine temperature conversions."""

import pytest

from unit_converter import ConvertError, convert, temperature


def test_seventy_two_fahrenheit_anchor():
    assert temperature.convert(72, "F", "C") == pytest.approx(22.2222, abs=1e-4)


def test_celsius_to_kelvin_offset():
    assert temperature.convert(0, "C", "K") == pytest.approx(273.15, abs=1e-12)


def test_boiling_point_freezing_point():
    assert temperature.convert(212, "F", "C") == pytest.approx(100.0, abs=1e-9)
    assert temperature.convert(32, "F", "C") == pytest.approx(0.0, abs=1e-9)


def test_kelvin_rankine_ratio():
    assert temperature.convert(1, "K", "R") == pytest.approx(9 / 5, rel=1e-12)


def test_round_trip_through_kelvin():
    for unit in ("C", "F", "R"):
        assert temperature.convert(temperature.convert(-40, unit, "K"), "K", unit) == pytest.approx(
            -40.0, abs=1e-9
        )


def test_case_insensitive_units():
    assert temperature.convert(72, "f", "c") == pytest.approx(22.2222, abs=1e-4)


def test_facade_dispatches_to_temperature():
    assert convert(0, "C", "F", category="temperature") == pytest.approx(32.0, abs=1e-9)


def test_unknown_unit_raises():
    with pytest.raises(ConvertError, match="unknown unit 'X'"):
        temperature.convert(0, "X", "C")
