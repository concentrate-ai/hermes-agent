"""Standalone unit conversion package — stdlib-only, no hermes core imports."""

from unit_converter import currency, length, mass, temperature
from unit_converter.currency import RATE_SNAPSHOT_DATE
from unit_converter.errors import ConvertError

_CONVERTERS = {
    "length": length.convert,
    "mass": mass.convert,
    "temperature": temperature.convert,
    "currency": currency.convert,
}


def convert(value: float, source: str, target: str, category: str = "length") -> float:
    """Convert ``value`` between units within one category."""
    try:
        converter = _CONVERTERS[category]
    except KeyError:
        raise ConvertError(f"unknown category {category!r}") from None
    return converter(value, source, target)


__all__ = ["ConvertError", "RATE_SNAPSHOT_DATE", "convert"]
