"""Property-based tests (hypothesis) — the factor-table typo catchers."""

import hypothesis.strategies as st
import pytest
from hypothesis import assume, given

from unit_converter import currency, length, mass, temperature

LENGTH_UNITS = sorted(length.FACTORS)
MASS_UNITS = sorted(mass.FACTORS)
TEMP_UNITS = sorted(temperature.TEMP_UNITS)
CURRENCIES = sorted(currency.RATES)

FLOATS = st.floats(min_value=0, allow_nan=False, allow_infinity=False, max_value=1e9)


# --- length -----------------------------------------------------------------


@given(FLOATS, st.sampled_from(LENGTH_UNITS), st.sampled_from(LENGTH_UNITS))
def test_length_round_trip(x, a, b):
    assert length.convert(length.convert(x, a, b), b, a) == pytest.approx(x, rel=1e-9, abs=1e-12)


@given(FLOATS, FLOATS, st.sampled_from(LENGTH_UNITS), st.sampled_from(LENGTH_UNITS))
def test_length_scales_linearly(x, y, a, b):
    # multiplicative: f(x + y) == f(x) + f(y)
    assert length.convert(x + y, a, b) == pytest.approx(
        length.convert(x, a, b) + length.convert(y, a, b), rel=1e-9, abs=1e-12
    )


@given(FLOATS, st.sampled_from(LENGTH_UNITS))
def test_length_identity(x, a):
    assert length.convert(x, a, a) == pytest.approx(x, rel=1e-15)


# --- mass -------------------------------------------------------------------


@given(FLOATS, st.sampled_from(MASS_UNITS), st.sampled_from(MASS_UNITS))
def test_mass_round_trip(x, a, b):
    assert mass.convert(mass.convert(x, a, b), b, a) == pytest.approx(x, rel=1e-9, abs=1e-12)


@given(FLOATS, FLOATS, st.sampled_from(MASS_UNITS), st.sampled_from(MASS_UNITS))
def test_mass_scales_linearly(x, y, a, b):
    assert mass.convert(x + y, a, b) == pytest.approx(
        mass.convert(x, a, b) + mass.convert(y, a, b), rel=1e-9, abs=1e-12
    )


@given(FLOATS, st.sampled_from(MASS_UNITS))
def test_mass_identity(x, a):
    assert mass.convert(x, a, a) == pytest.approx(x, rel=1e-15)


# --- temperature -------------------------------------------------------------


@given(
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
    st.sampled_from(TEMP_UNITS),
    st.sampled_from(TEMP_UNITS),
)
def test_temperature_round_trip(x, a, b):
    assert temperature.convert(temperature.convert(x, a, b), b, a) == pytest.approx(
        x, rel=1e-9, abs=1e-9
    )


@given(
    st.integers(-500, 500),
    st.integers(-500, 500),
    st.sampled_from(TEMP_UNITS),
    st.sampled_from(TEMP_UNITS),
)
def test_temperature_monotonic(a, b, u1, u2):
    # every temperature transform is strictly increasing — order survives
    colder, hotter = sorted((a, b))
    assume(colder < hotter)
    assert temperature.convert(colder, u1, u2) < temperature.convert(hotter, u1, u2)


# --- currency ----------------------------------------------------------------


@given(
    st.floats(min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False),
    st.sampled_from(CURRENCIES),
)
def test_currency_identity(x, a):
    assert currency.convert(x, a, a) == pytest.approx(x, rel=1e-15)


def test_currency_rates_positive():
    assert all(rate > 0 for rate in currency.RATES.values())


@given(
    st.floats(min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False),
    st.sampled_from(CURRENCIES),
    st.sampled_from(CURRENCIES),
    st.sampled_from(CURRENCIES),
)
def test_currency_triangle_consistency(x, a, b, c):
    # A -> B -> C -> A recovers the value
    through_b = currency.convert(x, a, b)
    through_c = currency.convert(through_b, b, c)
    assert currency.convert(through_c, c, a) == pytest.approx(x, rel=1e-9)
