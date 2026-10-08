"""Length conversions — pure factor table against the meter."""

from unit_converter.errors import ConvertError

# Multiplier that converts one unit into meters.
FACTORS: dict[str, float] = {
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "km": 1000.0,
    "in": 0.0254,  # exact by definition (1 in = 25.4 mm)
    "ft": 0.3048,  # exact by definition
    "yd": 0.9144,  # exact by definition
    "mi": 1609.344,  # exact by definition
    "nmi": 1852.0,  # exact by definition
}


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from one length unit to another."""
    try:
        return value * FACTORS[source] / FACTORS[target]
    except KeyError as e:
        raise ConvertError(f"unknown unit {e.args[0]!r}") from None
