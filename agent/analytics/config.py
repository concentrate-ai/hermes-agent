"""Threshold configuration for usage-analytics anomaly detection (PR #2).

Thresholds are configuration, not constants (spec §Anomaly alerts): a tuning
pass against real data can adjust them without touching detection logic.
Exports the dataclass `AlertThresholds` and the frozen default module
`DEFAULT_THRESHOLDS`.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AlertThresholds:
    """Anomaly-detection thresholds.

    Attributes:
        info_ratio: bucket spend above this multiple of the trailing-24h
            median fires an info alert.
        robust_z: MAD robust z-score above this fires a warning.
        dollar_floor: absolute USD spend floor — statistical alerts never
            fire below it; MAD=0 series elevation is judged by it directly.
        critical_multiplier: projected-period spend above this multiple of
            the budget fires critical.
        retry_storm_calls: calls with attempt > 1 or a rate-limit error
            class in one (axis, hour) cell needed to fire the critical
            retry-storm fingerprint.
        cold_start_min: minimum trailing observations before any statistical
            alert is considered (12 per spec).
        window_hours: trailing window used as the baseline.
    """

    info_ratio: float = 1.25
    robust_z: float = 3.5
    dollar_floor: float = 1.0
    critical_multiplier: float = 1.10
    retry_storm_calls: int = 5
    cold_start_min: int = 12
    window_hours: int = 24

    def with_expanded_floor(self, floor: float) -> "AlertThresholds":
        """Return a copy whose retry-storm branch also fires above `floor`."""
        return replace(self, dollar_floor=floor)


# Frozen module default; the aggregator clones via replace() rather than
# mutating this instance.
DEFAULT_THRESHOLDS = AlertThresholds()
