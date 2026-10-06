"""Tests for the usage-analytics aggregator (spec art_tZvdMeCj, PR #2 of 3).

Covers: every spec SQL query shape on a seeded db; NULL-cost annotation;
bucket-fill honesty; per-user honesty state; cache-savings math joined at
PricingEntry rates; empty-range and zero-events honesty states.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent.analytics import UsageAggregator, aggregate
from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


# 1700000000 = 2023-11-14T22:13:20Z — a known-aligned base for bucket math.
BASE = 1700000000.0
TWO_HOURS = 7200.0


def _seed(db, events):
    for kwargs in events:
        db.record_usage_event(**kwargs)


class TestP1Headline:
    def test_headline_totals_over_window(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "source": "cli",
                    "api_status": "ok",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_read_tokens": 2000,
                    "cache_write_tokens": 300,
                    "reasoning_tokens": 100,
                    "estimated_cost_usd": 0.05,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s2",
                    "ts": BASE + 120,
                    "api_status": "ok",
                    "input_tokens": 50,
                    "output_tokens": 50,
                    "estimated_cost_usd": 0.02,
                    "cost_status": "ok",
                },
            ],
        )
        payload = UsageAggregator(db).build_payload(BASE, BASE + TWO_HOURS)
        h = payload["headline"]
        assert h["api_calls"] == 2
        assert h["input_tokens"] == 1050
        assert h["output_tokens"] == 550
        assert h["cache_read_tokens"] == 2000
        assert h["cache_write_tokens"] == 300
        assert h["reasoning_tokens"] == 100
        assert h["est_cost_usd"] == pytest.approx(0.07)
        assert h["ok_rate"] == 1.0

    def test_null_cost_annotation_present(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": 0.01,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s2",
                    "ts": BASE + 60,
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": None,
                    "cost_status": "unknown",
                },
                {
                    "session_id": "s3",
                    "ts": BASE + 120,
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": None,
                    "cost_status": "unknown",
                },
            ],
        )
        h = UsageAggregator(db).build_payload(BASE, BASE + 600)["headline"]
        # 1 of 3 calls priced; SUM silently ignored the 2 NULLs.
        assert h["est_cost_usd"] == pytest.approx(0.01)
        assert h["cost_note"] == "cost unknown for 2 of 3 calls"

    def test_no_annotation_when_all_calls_priced(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "api_status": "ok",
                    "estimated_cost_usd": 0.02,
                    "cost_status": "ok",
                }
            ],
        )
        h = UsageAggregator(db).build_payload(BASE, BASE + 600)["headline"]
        assert "cost_note" not in h


class TestP2TrendBucketFill:
    def test_empty_hour_zero_filled_not_gap(self, db):
        base_hour = BASE - (BASE % 3600)  # align to hour start
        _seed(
            db,
            [
                # One event in the first window hour only; the second hour
                # has no events and must render as a zero bucket.
                {
                    "session_id": "s1",
                    "ts": base_hour + 10,
                    "api_status": "ok",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "estimated_cost_usd": 0.01,
                    "cost_status": "ok",
                }
            ],
        )
        since = base_hour
        until = base_hour + 7200  # exactly two hours
        payload = UsageAggregator(db).build_payload(since, until)
        hourly = payload["trend_hourly"]
        assert len(hourly) == 2
        filled = [c["api_calls"] for c in hourly]
        assert filled[0] == 1
        assert filled[1] == 0  # zero-filled, not a missing bucket
        assert hourly[1]["est_cost_usd"] == 0.0

    def test_daily_side_weekly_sum_match_hourly_sum(self, db):
        base_hour = BASE - (BASE % 3600)
        events = []
        for i in range(5):
            events.append({
                "session_id": f"s{i}",
                "ts": base_hour + i * 3600,
                "api_status": "ok",
                "input_tokens": 100,
                "output_tokens": 20,
                "estimated_cost_usd": 0.01,
                "cost_status": "ok",
            })
        _seed(db, events)
        payload = UsageAggregator(db).build_payload(base_hour, base_hour + 5 * 3600)
        hourly_sum = sum(c["est_cost_usd"] for c in payload["trend_hourly"])
        daily_sum = sum(c["est_cost_usd"] for c in payload["trend_daily"])
        assert hourly_sum == pytest.approx(daily_sum)


class TestP3PerModel:
    def test_model_breakdown_and_drill(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "model": "claude-opus-4-8",
                    "provider": "anthropic",
                    "api_status": "ok",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "estimated_cost_usd": 0.10,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s2",
                    "ts": BASE + 60,
                    "model": "claude-opus-4-8",
                    "provider": "anthropic",
                    "api_status": "error",
                    "error_class": "rate_limit",
                    "attempt": 2,
                    "input_tokens": 100,
                    "estimated_cost_usd": 0.01,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s3",
                    "ts": BASE + 120,
                    "model": "gpt-x",
                    "provider": "openai",
                    "api_status": "ok",
                    "input_tokens": 50,
                    "estimated_cost_usd": 0.005,
                    "cost_status": "ok",
                },
            ],
        )
        payload = UsageAggregator(db).build_payload(BASE, BASE + 600)
        per_model = payload["per_model"]
        assert len(per_model) == 2
        top = per_model[0]
        assert top["model"] == "claude-opus-4-8"  # ordered by est_cost DESC
        assert top["api_calls"] == 2
        assert top["est_cost_usd"] == pytest.approx(0.11)
        assert top["est_cost_per_call"] == pytest.approx(0.055)

        drill = UsageAggregator(db)._model_drill(  # noqa: SLF001 — internal drill shape
            "claude-opus-4-8", BASE, BASE + 600
        )
        assert drill["model"] == "claude-opus-4-8"
        assert len(drill["daily"]) == 1
        assert drill["errors_by_class"] == [{"error_class": "rate_limit", "calls": 1}]


class TestP4Tenants:
    def test_per_source_populated(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "source": "cli",
                    "api_status": "ok",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "estimated_cost_usd": 0.02,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s2",
                    "ts": BASE + 60,
                    "source": "api",
                    "api_status": "ok",
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "estimated_cost_usd": 0.05,
                    "cost_status": "ok",
                },
            ],
        )
        sources = UsageAggregator(db).build_payload(BASE, BASE + 600)["per_source"]
        assert {s["source"]: s["api_calls"] for s in sources} == {"cli": 1, "api": 1}
        by_src = {s["source"]: s["total_tokens"] for s in sources}
        assert by_src == {"cli": 150, "api": 300}

    def test_per_user_honest_state_when_not_backfilled(self, db):
        # All events have NULL user_id — the axis does not exist yet.
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "source": "cli",
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": 0.01,
                    "cost_status": "ok",
                }
            ],
        )
        pu = UsageAggregator(db).build_payload(BASE, BASE + 600)["per_user"]
        assert pu == {"state": "not_yet_populated", "entries": []}

    def test_per_user_populated_when_backfilled(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "source": "api",
                    "user_id": "u1",
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": 0.01,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s2",
                    "ts": BASE + 60,
                    "source": "api",
                    "user_id": "u1",
                    "api_status": "ok",
                    "input_tokens": 20,
                    "estimated_cost_usd": 0.02,
                    "cost_status": "ok",
                },
                {
                    "session_id": "s3",
                    "ts": BASE + 120,
                    "source": "api",
                    "api_status": "ok",
                    "input_tokens": 5,
                    "estimated_cost_usd": 0.005,
                    "cost_status": "ok",
                },
            ],
        )
        pu = UsageAggregator(db).build_payload(BASE, BASE + 600)["per_user"]
        assert pu["state"] == "populated"
        assert len(pu["entries"]) == 1
        assert pu["entries"][0]["user_id"] == "u1"

    def test_per_user_no_events_state(self, db):
        pu = UsageAggregator(db).build_payload(BASE, BASE + 600)["per_user"]
        assert pu["state"] == "no_events_in_range"


class TestP5CacheEconomics:
    def test_cache_hit_rate_and_python_savings(self, db, monkeypatch):
        # 2M cached-read tokens at the docs entry's known rates:
        # full price 2M * input_rate/1M minus actual 2M * cache_read_rate/1M
        # for claude-opus-4-8: input 5.00, cache-read 0.50 → savings = 9.00 USD
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "model": "claude-opus-4-8",
                    "provider": "anthropic",
                    "api_status": "ok",
                    "input_tokens": 1_000_000,
                    "cache_read_tokens": 2_000_000,
                    "estimated_cost_usd": 1.0,
                    "cost_status": "ok",
                    "pricing_version": "official-docs-snapshot",
                }
            ],
        )
        econ = UsageAggregator(db).build_payload(BASE, BASE + 600)["cache_economics"]
        assert len(econ["days"]) == 1
        assert econ["days"][0]["token_hit_rate"] == pytest.approx(2 / 3, abs=1e-3)
        day = sorted(econ["cache_savings_usd"])[0]
        saved = econ["cache_savings_usd"][day]
        assert saved == pytest.approx(9.0, abs=0.01)
        assert econ["pricing_versions"] == ["official-docs-snapshot"]


class TestP6Errors:
    def test_error_breakdown_and_retry_storm_sessions(self, db):
        events = []
        # 6 retry rows in one session-hour → retry-storm fingerprint.
        for i in range(6):
            events.append({
                "session_id": "storm",
                "ts": BASE + i,
                "api_status": "error",
                "error_class": "rate_limit",
                "attempt": i + 2,
                "input_tokens": 10,
                "estimated_cost_usd": 0.0,
                "cost_status": "ok",
            })
        # One clean row so the denominator for pct is nonzero and clean calls exist.
        events.append({
            "session_id": "calm",
            "ts": BASE + 60,
            "api_status": "ok",
            "input_tokens": 10,
            "estimated_cost_usd": 0.0,
            "cost_status": "ok",
        })
        _seed(db, events)
        errs = UsageAggregator(db).build_payload(BASE, BASE + 600)["errors"]
        statuses = {b["api_status"]: b["calls"] for b in errs["breakdown"]}
        assert statuses.get("error") == 6
        assert statuses.get("ok") == 1
        assert errs["retry_storm_sessions"] == ["storm"]


class TestEmptyRange:
    def test_zero_events_zero_filled_and_empty_panels(self, db):
        payload = UsageAggregator(db).build_payload(BASE, BASE + 7200)
        assert payload["headline"]["api_calls"] == 0
        assert payload["headline"]["est_cost_usd"] is None
        assert len(payload["trend_hourly"]) == 2  # zero-filled buckets
        assert all(c["api_calls"] == 0 for c in payload["trend_hourly"])
        assert payload["per_model"] == []
        assert payload["per_source"] == []
        assert payload["per_user"]["state"] == "no_events_in_range"
        assert payload["errors"]["retry_storm_sessions"] == []

    def test_provided_range_outside_all_events(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "api_status": "ok",
                    "input_tokens": 10,
                    "estimated_cost_usd": None,
                    "cost_status": "unknown",
                }
            ],
        )
        payload = UsageAggregator(db).build_payload(
            BASE + 86400 * 30, BASE + 86400 * 31
        )
        assert payload["headline"]["api_calls"] == 0
        assert "cost_note" not in payload["headline"]
        assert payload["per_user"]["state"] == "no_events_in_range"


class TestPayloadJson:
    def test_payload_json_serializable(self, db):
        _seed(
            db,
            [
                {
                    "session_id": "s1",
                    "ts": BASE,
                    "source": "cli",
                    "user_id": "u1",
                    "model": "m",
                    "api_status": "ok",
                    "input_tokens": 5,
                    "estimated_cost_usd": 0.001,
                    "cost_status": "ok",
                }
            ],
        )
        payload = UsageAggregator(db).build_payload(BASE, BASE + 600)
        dumped = json.dumps(payload)
        assert json.loads(dumped)["headline"]["api_calls"] == 1
