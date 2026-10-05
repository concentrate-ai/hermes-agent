"""Tests for the usage_events analytics table (spec art_tZvdMeCj §Verification).

Covers: additive migration on a pre-existing db (no data loss),
fault-isolation of record_usage_event, and happy-path capture.
"""

import re
import sqlite3
import time

import pytest

from hermes_state import SCHEMA_SQL, SessionDB


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


def _production_shaped_db(tmp_path):
    """Create a pre-dashboards db: SCHEMA_SQL minus the usage_events block."""
    legacy_sql = SCHEMA_SQL[
        SCHEMA_SQL.index("CREATE TABLE IF NOT EXISTS schema_version"):
        SCHEMA_SQL.index("-- Token Usage Analytics Dashboard")
    ]
    db_path = tmp_path / "legacy_state.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(legacy_sql)
    return db_path, conn


class TestAdditiveMigration:
    def test_opening_preexisting_db_creates_usage_events_with_no_data_loss(self, tmp_path):
        db_path, conn = _production_shaped_db(tmp_path)
        # Seed production-shaped data first.
        conn.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
            ("s1", "cli", time.time()),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("s1", "user", "hello", time.time()),
        )
        conn.commit()
        sessions_before = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        messages_before = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()

        # Opening the app runs reconcile against SCHEMA_SQL.
        db = SessionDB(db_path=db_path)
        try:
            # Table and both indexes exist.
            tables = {
                r[0]
                for r in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "usage_events" in tables
            assert "sessions" in tables and "messages" in tables
            indexes = {
                r[0]
                for r in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            assert "idx_usage_events_ts" in indexes
            assert "idx_usage_events_model_ts" in indexes
            # No data loss.
            assert (
                db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                == sessions_before
                == 1
            )
            assert (
                db._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                == messages_before
                == 1
            )
            # Events table is empty — no backfill.
            assert db._conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 0
        finally:
            db.close()

    def test_schema_columns_match_spec_order(self):
        spec_cols = [
            "id", "ts", "session_id", "source", "user_id", "model", "provider",
            "billing_mode", "api_status", "error_class", "attempt",
            "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
            "cost_status", "cost_source", "pricing_version", "raw_usage",
        ]
        m = re.search(
            r"CREATE TABLE IF NOT EXISTS usage_events \((.*?)\);",
            SCHEMA_SQL,
            re.DOTALL,
        )
        body = m.group(1)
        # Strip index/table lines outside the table body; extract leading
        # column names from each non-constraint definition line.
        lines = [
            ln.strip().split()[0]
            for ln in body.splitlines()
            if ln.strip() and not ln.strip().upper().startswith(("PRIMARY", "UNIQUE", "CHECK", "FOREIGN"))
        ]
        assert lines == spec_cols


class TestRecordUsageEvent:
    def test_happy_path_inserts_one_row_with_expected_fields(self, db):
        db.record_usage_event(
            session_id="s1",
            ts=1700000000.0,
            source="cli",
            model="claude-sonnet-4-5",
            provider="anthropic",
            billing_mode=None,
            api_status="ok",
            attempt=1,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=200,
            cache_write_tokens=10,
            reasoning_tokens=5,
            estimated_cost_usd=0.0123,
            cost_status="ok",
            cost_source="docs snapshot",
            pricing_version="pv-1",
            raw_usage='{"input_tokens": 100}',
        )
        row = dict(
            zip(
                [c[1] for c in db._conn.execute(
                    "PRAGMA table_info(usage_events)").fetchall()],
                db._conn.execute(
                    "SELECT * FROM usage_events WHERE session_id='s1'"
                ).fetchone(),
            )
        )
        assert row["ts"] == 1700000000.0
        assert row["source"] == "cli"
        assert row["model"] == "claude-sonnet-4-5"
        assert row["provider"] == "anthropic"
        assert row["api_status"] == "ok"
        assert row["attempt"] == 1
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["cache_read_tokens"] == 200
        assert row["cache_write_tokens"] == 10
        assert row["reasoning_tokens"] == 5
        assert row["estimated_cost_usd"] == pytest.approx(0.0123)
        assert row["cost_status"] == "ok"
        assert row["pricing_version"] == "pv-1"

    def test_failure_does_not_touch_session_state(self, db):
        db.ensure_session("s1", source="cli", model="m1")
        db.update_token_counts("s1", input_tokens=10, output_tokens=5)
        sessions_before = db._conn.execute(
            "SELECT input_tokens, output_tokens FROM sessions WHERE id='s1'"
        ).fetchone()

        # Fault injection: force the insert to fail by closing the conn
        # used by record_usage_event via a corrupting monkeypatch on
        # _execute_write.
        original = db._execute_write

        def _failing_write(fn):
            raise sqlite3.OperationalError("forced analytics failure")

        db._execute_write = _failing_write
        try:
            with pytest.raises(sqlite3.OperationalError):
                db.record_usage_event(session_id="s1", ts=time.time())
        finally:
            db._execute_write = original

        # Session state identical; no rows recorded on the retry.
        assert (
            db._conn.execute(
                "SELECT input_tokens, output_tokens FROM sessions WHERE id='s1'"
            ).fetchone()
            == sessions_before
        )
        assert db._conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 0

        # And a later successful insert works (state not corrupted).
        db.record_usage_event(session_id="s1", ts=time.time(), api_status="ok")
        assert db._conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 1
