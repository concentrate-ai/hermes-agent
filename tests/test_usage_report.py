"""Tests for the usage-report renderer + CLI entry (spec art_tZvdMeCj §Verification).

Acceptance: seeded-db render populates every panel and the anomaly feed in
under a few seconds; a zero-events range renders zero-filled buckets and
honest empty states; --db-path isolates from the real state.db.
"""

import json
import time

import pytest

from hermes_cli.usage_report import build_report_payload, write_report
from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    session_db = SessionDB(db_path=tmp_path / "test_state.db")
    yield session_db
    session_db.close()


def _seed_events(db: SessionDB) -> float:
    """20 sessions, mixed sources/models, spread over multiple days.

    Returns the window start (epoch) the events are spread after. One axis
    gets a retry-heavy hour so the anomaly feed has something to surface.
    """
    start = 1_700_000_000.0  # fixed epoch so tests are deterministic
    sources = ["cli", "api_server", "cron", "telegram"]
    models = ["gpt-4o", "claude-sonnet-4-5", "gemini-2.0-flash"]
    session_ids = []
    for i in range(20):
        session_id = f"sess-{i:03d}"
        session_ids.append(session_id)
        ts = start + (i % 4) * 86400 + (i % 7) * 3600
        db.record_usage_event(
            session_id=session_id,
            ts=ts,
            source=sources[i % len(sources)],
            model=models[i % len(models)],
            provider="test",
            api_status="ok" if i % 5 else "error",
            error_class=None if i % 5 else "rate_limit",
            attempt=2 if i % 6 == 0 else 1,
            input_tokens=1000 + i * 100,
            output_tokens=500 + i * 50,
            cache_read_tokens=200 + i * 20,
            cache_write_tokens=100 + i * 10,
            reasoning_tokens=50 + i * 5,
            estimated_cost_usd=0.01 + i * 0.001,
            cost_status="ok",
            cost_source="test",
            pricing_version="test-v1",
        )
    # Background cron spend, hourly, so the storm hour below has a
    # legitimate trailing baseline (detect() requires >= 12 trailing
    # observations before any cell is classified — cold-start guard).
    storm_ts = start + 14 * 3600
    for h in range(14):
        db.record_usage_event(
            session_id="sess-cron-bg",
            ts=start + h * 3600 + 60,
            source="cron",
            model=models[0],
            provider="test",
            api_status="ok",
            input_tokens=500,
            output_tokens=100,
            estimated_cost_usd=0.01,
            cost_status="ok",
            pricing_version="test-v1",
        )
    # A retry-storm cell: 5 rate-limited attempts in one hour on one session.
    for n in range(5):
        db.record_usage_event(
            session_id=session_ids[0],
            ts=storm_ts + n,
            source="cron",
            model=models[0],
            provider="test",
            api_status="error",
            error_class="rate_limit",
            attempt=n + 2,
            input_tokens=100,
            output_tokens=0,
            estimated_cost_usd=0.5,
            cost_status="ok",
            pricing_version="test-v1",
        )
    return start


class TestSeededRender:
    """Render-from-seeded-db: all panels + anomaly feed, fast."""

    def test_seeded_db_renders_all_panels_quickly(self, db, tmp_path):
        since = _seed_events(db)
        out = tmp_path / "report.html"

        t0 = time.monotonic()
        path, warning_line = write_report(db, since, since + 10 * 86400, out)
        elapsed = time.monotonic() - t0

        html = out.read_text(encoding="utf-8")
        assert path == out
        # All panels render with content (not the honest empty placeholders).
        assert "user attribution not yet populated" in html  # P4b honesty state
        assert "no events in range" not in html
        assert "Per-Model" in html and "Per-Tenant" in html
        assert "Cache Economics" in html and "Anomaly Feed" in html
        assert "Per-Model Drill" in html
        # The retry-storm session seeded above surfaces in the feed.
        assert "retry calls in one hour" in html
        assert "retry-storm sessions" in html
        # Payload is embedded for reproducibility.
        assert "payload-json" in html
        # Perf budget: "under a few seconds" (spec §Verification).
        assert elapsed < 5.0, f"render took {elapsed:.2f}s"
        assert warning_line.startswith("Usage anomalies detected")

    def test_build_report_payload_shape(self, db):
        since = _seed_events(db)
        payload, alert_dicts, warning = build_report_payload(
            db, since, since + 10 * 86400
        )
        assert payload["headline"]["api_calls"] == 39  # 20 + 5 storm + 14 bg
        assert payload["per_model"], "per-model table must populate"
        assert payload["per_source"], "per-source table must populate"
        assert payload["model_drills"], "drill cards must populate"
        assert payload["trend_hourly"], "hourly trend must populate"
        assert payload["trend_daily"], "daily trend must populate"
        assert alert_dicts, "anomaly feed must have the retry storm"
        assert any(a["severity"] == "critical" for a in alert_dicts)
        assert "1 critical" in warning


class TestZeroEventsRange:
    """A window with zero events renders honest empties, not fake zeros."""

    def test_zero_events_renders_honest_states(self, db, tmp_path):
        _seed_events(db)
        # Window entirely after every seeded event — zero events in range.
        since = 1_700_000_000.0 + 100 * 86400
        out = tmp_path / "empty.html"
        _, warning_line = write_report(db, since, since + 86400, out)

        html = out.read_text(encoding="utf-8")
        assert warning_line == "No usage anomalies detected."
        # Zero-filled hourly buckets exist (bucket-filled, not gaps).
        assert "Hourly Trend" in html
        assert "2024-02-23" in html  # window start renders in the header line
        # Panels present with empty-state content, not fabricated numbers.
        assert "no events in range" in html
        assert "no anomalies detected" in html
        assert "no drill data" in html

    def test_zero_events_zero_filled_buckets(self, db):
        since = 1_700_000_000.0 + 100 * 86400
        payload, alert_dicts, _ = build_report_payload(db, since, since + 3 * 3600)
        buckets = [r["bucket"] for r in payload["trend_hourly"]]
        assert len(buckets) == 3, "each covered hour must be a bucket"
        assert all(
            r["input_side"] == 0 and r["est_cost_usd"] == 0.0
            for r in payload["trend_hourly"]
        )
        assert alert_dicts == []


class TestDbPathOverride:
    """--db-path isolates from the default state.db (test isolation)."""

    def test_report_reads_only_overridden_db(self, tmp_path):
        db_a = SessionDB(db_path=tmp_path / "a.db")
        db_b = SessionDB(db_path=tmp_path / "b.db")
        try:
            start = 1_700_000_000.0
            db_a.record_usage_event(
                session_id="in-a",
                ts=start + 100,
                source="cli",
                model="m-a",
                provider="test",
                input_tokens=10,
                estimated_cost_usd=0.01,
            )
            payload_a, _, _ = build_report_payload(db_a, start, start + 3600)
            payload_b, _, _ = build_report_payload(db_b, start, start + 3600)
            assert payload_a["headline"]["api_calls"] == 1
            assert payload_b["headline"]["api_calls"] == 0
        finally:
            db_a.close()
            db_b.close()


class TestCliWindowParsing:
    def test_empty_window_rejected(self, tmp_path):
        import argparse

        from hermes_cli.usage_report import _resolve_window

        args = argparse.Namespace(
            days=7, since="2000-01-02T00:00:00Z", until="2000-01-01T00:00:00Z"
        )
        with pytest.raises(SystemExit):
            _resolve_window(args)

    def test_iso_and_epoch_args_parse(self):
        import argparse

        from hermes_cli.usage_report import _resolve_window

        args = argparse.Namespace(
            days=2, since="1700000000", until="1700200000"
        )
        since_ts, until_ts = _resolve_window(args)
        assert since_ts == 1_700_000_000.0
        assert until_ts == 1_700_200_000.0
