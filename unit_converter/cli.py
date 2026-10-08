"""`unit-convert` command-line entry point."""

from __future__ import annotations

import argparse
import sys

from unit_converter import currency, errors, length, mass, temperature

_CURRENCY_NOTE = f"(static rates as of {currency.RATE_SNAPSHOT_DATE})"

# Display symbols for temperature units in CLI output.
_TEMP_SYMBOLS = {"C": "°C", "F": "°F", "K": "K", "R": "°R"}


class _Parser(argparse.ArgumentParser):
    """argparse that prints one error line instead of usage + message."""

    def error(self, message: str) -> None:
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)


def _is_temperature(unit: str) -> bool:
    return unit.upper() in temperature.TEMP_UNITS


def _is_currency(unit: str) -> bool:
    return (
        unit.isalpha()
        and len(unit) == 3
        and unit.upper() in currency.RATES
    )


def _is_known(unit: str) -> bool:
    return (
        _is_temperature(unit)
        or _is_currency(unit)
        or unit in length.FACTORS
        or unit in mass.FACTORS
    )


def _dispatch(value: float, source: str, target: str) -> tuple[float, str, str, bool]:
    """Resolve the category and convert. Returns (result, src, dst, is_currency)."""
    if _is_temperature(source) and _is_temperature(target):
        result = temperature.convert(value, source, target)
        return result, _TEMP_SYMBOLS[source.upper()], _TEMP_SYMBOLS[target.upper()], False
    if _is_currency(source) and _is_currency(target):
        result = currency.convert(value, source, target)
        return result, source.upper(), target.upper(), True
    if source in length.FACTORS and target in length.FACTORS:
        return length.convert(value, source, target), source, target, False
    if source in mass.FACTORS and target in mass.FACTORS:
        return mass.convert(value, source, target), source, target, False
    unknown = source if not _is_known(source) else target
    raise errors.ConvertError(f"unknown unit {unknown!r}")


def _format_number(x: float) -> str:
    """Fixed-point with trailing zeros trimmed, keeping at least one decimal."""
    text = f"{x:.9f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `unit-convert` console script. Returns the exit code."""
    parser = _Parser(
        prog="unit-convert",
        description="Convert a value between two units (length, mass, temperature, currency).",
    )
    parser.add_argument("value", help="numeric value to convert, e.g. 5 or 72")
    parser.add_argument("source", help="unit to convert from, e.g. km, F, USD")
    parser.add_argument("target", help="unit to convert to, e.g. mi, C, EUR")
    args = parser.parse_args(argv)

    try:
        value = float(args.value)
    except ValueError:
        print(f"error: invalid number {args.value!r}", file=sys.stderr)
        return 2

    try:
        result, src, dst, is_currency = _dispatch(value, args.source, args.target)
    except errors.ConvertError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    note = f" {_CURRENCY_NOTE}" if is_currency else ""
    print(f"{args.value} {src} = {_format_number(result)} {dst}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
