"""Example-based tests for mass conversions."""

import pytest

from unit_converter import ConvertError, convert, mass


def test_pound_anchor():
    assert mass.convert(1, "kg", "lb") == pytest.approx(2.20462262, rel=1e-8)


def test_kilogram_is_base_unit():
    assert mass.convert(98.7, "kg", "kg") == 98.7


def test_exact_defined_factors():
    assert mass.convert(1, "kg", "g") == 1000.0
    assert mass.convert(1, "t", "kg") == 1000.0
    assert mass.convert(1, "lb", "oz") == pytest.approx(16.0, rel=1e-12)
    assert mass.convert(1, "mg", "g") == pytest.approx(0.001, rel=1e-12)


def test_facade_dispatches_to_mass():
    assert convert(3, "t", "kg", category="mass") == 3000.0


def test_unknown_unit_raises():
    with pytest.raises(ConvertError, match="unknown unit 'stones'"):
        mass.convert(1, "stones", "kg")
