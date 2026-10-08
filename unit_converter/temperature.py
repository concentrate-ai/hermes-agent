"""Temperature conversions — affine, keyed through kelvin.

Temperature offsets make pure factor tables wrong here (0 °C is not 0 K),
so each unit gets an explicit to_kelvin/from_kelvin pair instead of a
multiplier. The generic factor path in length.py/mass.py must never be
used for temperature.
"""

from unit_converter.errors import ConvertError

TEMP_UNITS: frozenset[str] = frozenset({"C", "F", "K", "R"})


def to_kelvin(value: float, unit: str) -> float:
    """Convert ``value`` from ``unit`` into kelvin."""
    u = unit.upper()
    if u == "K":
        return value
    if u == "C":
        return value + 273.15
    if u == "F":
        return (value + 459.67) * 5 / 9
    if u == "R":
        return value * 5 / 9
    raise ConvertError(f"unknown unit {unit!r}")


def from_kelvin(value: float, unit: str) -> float:
    """Convert a kelvin ``value`` into ``unit``."""
    u = unit.upper()
    if u == "K":
        return value
    if u == "C":
        return value - 273.15
    if u == "F":
        return value * 9 / 5 - 459.67
    if u == "R":
        return value * 9 / 5
    raise ConvertError(f"unknown unit {unit!r}")


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from one temperature unit to another via kelvin."""
    return from_kelvin(to_kelvin(value, source), target)
