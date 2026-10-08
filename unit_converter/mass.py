"""Mass conversions — pure factor table against the kilogram."""

from unit_converter.errors import ConvertError

# Multiplier that converts one unit into kilograms.
FACTORS: dict[str, float] = {
    "mg": 1e-6,
    "g": 0.001,
    "kg": 1.0,
    "t": 1000.0,  # metric tonne
    "oz": 0.028349523125,  # exact by definition (1 lb = 16 oz)
    "lb": 0.45359237,  # exact by definition
    "st": 6.35029318,  # stone, exact by definition
    "ton": 907.18474,  # US short ton, exact by definition
}


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from one mass unit to another."""
    try:
        return value * FACTORS[source] / FACTORS[target]
    except KeyError as e:
        raise ConvertError(f"unknown unit {e.args[0]!r}") from None
