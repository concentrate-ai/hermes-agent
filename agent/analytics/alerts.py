"""Anomaly alert detection for the usage dashboard (spec art_tZvdMeCj).

Pure-function detect() over hourly (axis, bucket) spend cells aggregated from
usage_events — SQLite has no stddev/median window functions, and this math is
small enough that it belongs in Python. Delivery (dashboard anomaly feed +
printed warning) lives elsewhere; routing never touches this math.

Signals, in severity order, on each (axis, hour) cell against its trailing
window of cell history:
    critical — retry-storm fingerprint: >= retry_storm_calls retry calls in
               one hour (fires regardless of spend); or projected-period
               spend over the budget (with_budget aware callers only).
    warning  — robust z-score (MAD) > threshold AND spend >= dollar floor.
    info     — spend > median * info_ratio (watch signal, never pages).

Honesty rules locked by tests: fewer than cold_start_min trailing
observations means no statistical alert (a bare window can't claim a
baseline); MAD = 0 never divides by zero — spend elevation falls back to the
absolute dollar floor.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from agent.analytics.config import DEFAULT_THRESHOLDS, AlertThresholds


@dataclass(frozen=True)
class Alert:
    """One anomaly alert cell."""

    axis: str
    bucket: str
    severity: str  # critical | warning | info
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "axis": self.axis,
            "bucket": self.bucket,
            "severity": self.severity,
            "message": self.message,
        }


def _robust_z(spend: float, baseline: list[float]) -> float:
    """MAD-based robust z-score; falls back to 0.0 for a degenerate MAD=0.

    A constant baseline cannot claim a deviation coefficient (division by a
    zero MAD is not defined), so elevation on such series is judged only by
    the absolute dollar floor — never by dividing by zero — per spec.
    """
    if not baseline:
        return 0.0
    med = statistics.median(baseline)
    mad = statistics.median([abs(b - med) for b in baseline])
    if mad == 0:
        # Degenerate constant baseline: the deviation coefficient is
        # unbounded — any real elevation exceeds it infinitely, so a spike
        # above the median reports infinite deviation (never a div-zero).
        return float("inf") if spend > med else 0.0
    return 0.6745 * (spend - med) / mad


def _classify_cell(
    cur: Mapping[str, Any],
    baseline: list[float],
    thresholds: AlertThresholds,
) -> Alert | None:
    """Severity for one cell against its trailing baseline, or None."""
    spend = float(cur.get("spend") or 0.0)
    retries = int(cur.get("retries") or 0)

    # Retry-storm fingerprint first: cost + stable requests + attempts>1 is
    # catchable before the invoice regardless of what dollar z-score says.
    if retries >= thresholds.retry_storm_calls:
        return Alert(
            axis=str(cur["axis"]),
            bucket=str(cur["bucket"]),
            severity="critical",
            message=f"{retries} retry calls in one hour",
        )

    med = statistics.median(baseline)
    robust_z = _robust_z(spend, baseline)
    relative_elevated = spend > med * thresholds.info_ratio

    if robust_z > thresholds.robust_z and spend >= thresholds.dollar_floor:
        return Alert(
            axis=str(cur["axis"]),
            bucket=str(cur["bucket"]),
            severity="warning",
            message=f"spend {spend:.2f} vs median {med:.2f}",
        )
    # MAD=0 (constant spend, common at low volume): the ±floor branch, not a
    # crash, is where real elevation gets judged.
    if (
        spend > thresholds.dollar_floor
        and med <= thresholds.dollar_floor
        and robust_z == 0.0
        and med == 0.0
    ):
        return Alert(
            axis=str(cur["axis"]),
            bucket=str(cur["bucket"]),
            severity="info",
            message=f"first spend {spend:.2f} above zero baseline",
        )
    if relative_elevated:
        return Alert(
            axis=str(cur["axis"]),
            bucket=str(cur["bucket"]),
            severity="info",
            message=f"elevated spend {spend:.2f}",
        )
    return None


def detect(
    hours: Iterable[Mapping[str, Any]],
    thresholds: AlertThresholds = DEFAULT_THRESHOLDS,
) -> list[Alert]:
    """Detect anomaly alerts over hourly (axis, bucket) spend cells.

    ``hours`` rows come from HOURLY_SQL: {bucket, axis, spend, retries,
    calls}. The trailing-24h baseline excludes the current cell. Cold-start
    guard: fewer than ``cold_start_min`` observations in the baseline means
    no statistical alert fires — a short window can't claim a baseline.
    """
    by_axis: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for h in hours:
        by_axis[str(h["axis"])].append(h)

    alerts: list[Alert] = []
    # Bucket labels were verified unique per (axis, hour) above, so sorting
    # by label orders the series chronologically.
    for axis, series in by_axis.items():
        series = sorted(series, key=lambda h: str(h["bucket"]))
        window = thresholds.window_hours
        for i, cur in enumerate(series):
            # Trailing window, excludes the current cell.
            baseline_cells = series[max(0, i - window) : i]
            if len(baseline_cells) < thresholds.cold_start_min:
                continue
            baseline = [float(c.get("spend") or 0.0) for c in baseline_cells]
            alert = _classify_cell(cur, baseline, thresholds)
            if alert is not None:
                alerts.append(alert)
    return alerts


def detect_from_db(
    db,
    since_ts: float,
    thresholds: AlertThresholds = DEFAULT_THRESHOLDS,
) -> list[Alert]:
    """Fetch HOURLY_SQL rows from usage_events and run detect().

    ``since_ts`` is the window start (epoch seconds); aggregation SQL groups
    per hour bucket per axis (per-user when backfilled, per-source otherwise).
    Thresholds come from configuration — pass them anonymously per run.
    """
    sql = """
    SELECT strftime('%Y-%m-%d %H', ts, 'unixepoch') AS bucket,
           COALESCE(user_id, source) AS axis,
           SUM(estimated_cost_usd) AS spend,
           SUM(attempt > 1) AS retries,
           COUNT(*) AS calls
    FROM usage_events
    WHERE ts >= :since_ts
    GROUP BY bucket, axis
    """
    rows = db._conn.execute(sql, {"since_ts": since_ts}).fetchall()  # noqa: SLF001
    hours: list[dict[str, Any]] = []
    for bucket, axis, spend, retries, calls in rows:
        hours.append({
            "bucket": bucket,
            "axis": axis if axis is not None else "unknown",
            "spend": float(spend) if spend is not None else 0.0,
            "retries": int(retries or 0),
            "calls": int(calls),
        })
    return detect(hours, thresholds=thresholds)


def alerts_payload(alerts: Iterable[Alert]) -> list[dict[str, str]]:
    """Serialize alerts for the anomaly feed — JSON-ready dicts only."""
    return [a.as_dict() for a in alerts]


def format_warning_line(alerts: Iterable[Alert]) -> str:
    """Printed warning line for the CLI run (spec locked round-1 delivery)."""
    alerts = list(alerts)
    if not alerts:
        return "No usage anomalies detected."
    critical = sum(1 for a in alerts if a.severity == "critical")
    warning = sum(1 for a in alerts if a.severity == "warning")
    info = len(alerts) - critical - warning
    parts = []
    if critical:
        parts.append(f"{critical} critical")
    if warning:
        parts.append(f"{warning} warning")
    if info:
        parts.append(f"{info} info")
    return "Usage anomalies detected: " + ", ".join(parts)
