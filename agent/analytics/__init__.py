"""Usage-analytics package (spec art_tZvdMeCj, PR #2 of 3).

The aggregator reads the usage_events table written by PR #2's capture hook
and emits a JSON-ready payload for the dashboard; alerts.py computes anomaly
alerts as pure functions over hourly buckets.
"""

from agent.analytics.aggregator import UsageAggregator, aggregate
from agent.analytics.alerts import Alert, detect, format_warning_line

__all__ = [
    "UsageAggregator",
    "aggregate",
    "Alert",
    "detect",
    "format_warning_line",
]
