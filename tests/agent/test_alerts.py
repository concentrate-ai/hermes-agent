"""Tests for anomaly alert detection (spec art_tZvdMeCj, PR #2 of 3).

Covers the synthetic-series acceptance criteria: flat hourly spend with one
10x spike fires a warning on the spike hour only; MAD=0 series hits the
floor rule without crashing; 5 retries in one hour fires critical regardless
of spend; changing threshold config alters alert output (two fixture
configs); the cold-start guard and per-axis isolation.
"""

import pytest

from agent.analytics import detect, format_warning_line
from agent.analytics.config import AlertThresholds


def _cells(spend_series, axis="cli", retries=0):
    """Hourly cells over consecutive hours starting 2026-10-01 00:00.

    Labels never recycle past hour 24 (day rolls over), so detect's bucket
    sort始终 matches arrival order.
    """
    return [
        {
            "bucket": "2026-10-%02d %02d:00" % (1 + i // 24, i % 24),
            "axis": axis,
            "spend": s,
            "retries": retries if isinstance(retries, int) else retries[i],
            "calls": 10,
        }
        for i, s in enumerate(spend_series)
    ]


class TestFlatWithSpike:
    def test_flat_spend_plus_10x_spike_fires_warning_on_spike_hour_only(self):
        # 24 flat hours at $0.10, then one hour at $1.00 (10x). MAD=0 on the
        # flat baseline -> unbounded deviation -> warning on the spike hour
        # only (spend 1.00 clears the $1 dollar floor).
        alerts = detect(_cells([0.10] * 24 + [1.00]))
        warnings = [a for a in alerts if a.severity == "warning"]
        assert len(warnings) == 1
        assert warnings[0].bucket == "2026-10-02 00:00"
        assert warnings[0].axis == "cli"
        assert "1.00 vs median 0.10" in warnings[0].message

    def test_flat_spend_only_no_alerts(self):
        assert detect(_cells([0.10] * 30)) == []

    def test_spike_below_dollar_floor_does_not_fire(self):
        # 10x elevation but under the $1 floor: statistical alert suppressed.
        alerts = detect(_cells([0.010] * 24 + [0.050]))
        assert not any(a.severity == "warning" for a in alerts)


class TestColdStart:
    def test_cold_series_produces_no_statistical_alert(self):
        # Only 5 observations: the cold-start guard (< 12) suppresses every
        # statistical alert, no matter how dramatic the rise.
        cells = _cells([0.5 * i for i in range(5)])
        assert detect(cells) == []

    def test_first_eleven_warmed_hours_still_cold(self):
        spend = [1.00] * 11 + [5.00]
        assert detect(_cells(spend)) == []

    def test_cold_start_transitions_once_baseline_is_long_enough(self):
        # 12 flat hours then 20 spike hours: warnings fire on spike hours
        # i=12..23 whose baselines are still all-flat (MAD=0 -> unbounded).
        # From i=24 the baseline window mixes flats and spikes and stops
        # firing — the spike became the normal.
        spend = [0.10] * 12 + [1.00] * 20
        alerts = detect(_cells(spend))
        warnings = [a for a in alerts if a.severity == "warning"]
        assert len(warnings) == 12
        assert warnings[0].bucket == "2026-10-01 12:00"


class TestRetryStorm:
    def test_five_retries_fires_critical_even_at_zero_spend(self):
        cells = _cells([0.0] * 24)
        cells.append({
            "bucket": "2026-10-02 02:00",
            "axis": "cli",
            "spend": 0.0,
            "retries": 5,
            "calls": 10,
        })
        alerts = detect(cells)
        criticals = [a for a in alerts if a.severity == "critical"]
        assert len(criticals) == 1
        assert criticals[0].message == "5 retry calls in one hour"

    def test_four_retries_do_not_fire(self):
        cells = _cells([0.0] * 24)
        cells.append({
            "bucket": "2026-10-02 02:00",
            "axis": "cli",
            "spend": 0.0,
            "retries": 4,
            "calls": 10,
        })
        assert detect(cells) == []

    def test_retry_storm_threshold_is_config(self):
        cells = _cells([0.0] * 24)
        cells.append({
            "bucket": "2026-10-02 02:00",
            "axis": "cli",
            "spend": 0.0,
            "retries": 3,
            "calls": 10,
        })
        relaxed = AlertThresholds(retry_storm_calls=3)
        assert [a.severity for a in detect(cells, thresholds=relaxed)] == ["critical"]

    def test_retry_fires_at_warm_minimum_history(self):
        # The fingerprint is not statistical, but detect() still requires the
        # warmed baseline length before evaluating any cell; at exactly 12
        # trailing observations the retry cell fires.
        cells = _cells([0.0] * 12, retries=0)
        cells.append({
            "bucket": "b",
            "axis": "cli",
            "spend": 0.0,
            "retries": 5,
            "calls": 1,
        })
        assert [a.severity for a in detect(cells)] == ["critical"]


class TestMadZero:
    def test_mad_zero_series_no_crash_and_floor_rule_catches(self):
        # Flat-zero baseline (MAD=0) then real spend: no div-by-zero crash;
        # the $5 spend clears the dollar floor so the floor rule fires.
        alerts = detect(_cells([0.0] * 12 + [5.0] * 5))
        assert any(a.severity == "warning" for a in alerts)

    def test_mad_zero_first_spend_below_floor_falls_to_info(self):
        # $0.50 elevation over a zero baseline: under the $1 floor, but the
        # relative-elevation info branch catches it (spend > 0 * ratio).
        alerts = detect(_cells([0.0] * 12 + [0.5]))
        assert [a.severity for a in alerts] == ["info"]

    def test_mad_zero_multi_axis_isolated(self):
        # Two axes in one stream; a spike in one must not ghost onto the other.
        cells = _cells([0.0] * 24, axis="cli") + _cells([0.0] * 24, axis="api")
        cells[24 + 20] = {**cells[24 + 20], "spend": 1.0}  # mid-stream api-axis spike
        alerts = detect(cells)
        warnings = [a for a in alerts if a.severity == "warning"]
        assert len(warnings) == 1
        assert warnings[0].axis == "api"


class TestThresholdsConfig:
    def test_two_configs_alter_alert_output(self):
        # Tight: fires a warning on a 4x elevation over a flat baseline.
        # Loose: dollar floor placed above all spend — same series, no alert.
        spend = [0.10] * 24 + [0.40]  # 4x elevation
        tight = AlertThresholds(robust_z=1.0, dollar_floor=0.01, info_ratio=1.25)
        loose = AlertThresholds(robust_z=1.0, dollar_floor=1e6, info_ratio=1e6)
        tight_alerts = detect(_cells(spend), thresholds=tight)
        loose_alerts = detect(_cells(spend), thresholds=loose)
        assert [a.severity for a in tight_alerts] == ["warning"]
        assert loose_alerts == []


class TestFormatWarningLine:
    def test_empty_and_summary_lines(self):
        assert format_warning_line([]) == "No usage anomalies detected."
        line = format_warning_line(detect(_cells([0.0] * 12 + [5.0])))
        assert "warning" in line
