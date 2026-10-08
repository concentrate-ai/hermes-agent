"""Currency conversions against a static, dated snapshot.

The rates below are a hardcoded illustrative snapshot taken on
RATE_SNAPSHOT_DATE — NOT live data, and never fetched from the network.
The CLI prints the snapshot date alongside every currency result so the
output cannot be mistaken for current exchange rates. Tests assert
properties of this table (positivity, identity, triangle consistency),
not correctness of any real-world exchange rate.
"""

from unit_converter.errors import ConvertError

RATE_SNAPSHOT_DATE = "2026-10-01"

# 1 USD in target currency — illustrative snapshot, not live data.
RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.0,
    "CNY": 7.15,
    "INR": 83.5,
    "CAD": 1.36,
    "AUD": 1.52,
    "CHF": 0.88,
    "MXN": 17.9,
}


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from one snapshot currency to another."""
    try:
        # RATES maps 1 USD in target currency, so USD->EUR is value * RATES["EUR"].
        return value * RATES[target.upper()] / RATES[source.upper()]
    except KeyError as e:
        raise ConvertError(f"unknown currency {e.args[0]!r}") from None
