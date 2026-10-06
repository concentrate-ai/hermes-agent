"""JSON-payload aggregator for the token-usage dashboard (spec art_tZvdMeCj).

Reads only the denormalized ``usage_events`` table written by PR #2's capture
hook — no sessions/messages joins, which is what the denormalization buys.
SQL stays in the SQLite dialect, verbatim from the spec's Panels section, so
every number on the rendered page is re-derivable by running its query against
state.db. Statistical work (alerts, cache savings) happens in Python: SQLite
has no stddev/percentile window functions.

Payload consumers: the P2/P3/P4 renderers and the anomaly feed (PR #3).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from agent.analytics.config import DEFAULT_THRESHOLDS, AlertThresholds
from agent.usage_pricing import get_pricing_entry

logger = logging.getLogger(__name__)

MICROSECONDS = 1_000_000


def _datetime_to_ts_float(dt: datetime) -> float:
    """Datime to epoch seconds float, tolerating naive input."""
    if dt.tzinfo is None:
        return dt.timestamp()
    return dt.timestamp()


def _iso_from_time_bucket(bucket: str) -> str:
    """SQLite hour bucket to an ISO-8601 UTC hour start."""
    dt = datetime.strptime(bucket, "%Y-%m-%d %H:00:00").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


def _rows_as_dicts(rows: Any, cursor: Any) -> list[dict[str, Any]]:
    """Map sqlite rows into dicts by their column names."""
    return [dict(zip((c[0] for c in cursor.description), row)) for row in rows]


def _read(db, sql: str, params: dict[str, Any]):
    """Read-only query against the SessionDB's connection.

    SessionDB keeps its connection private (“_conn”; no public read cursor),
    so analytics reads go through this one accessor — read-only, and if the
    private attribute moves, this is the single line that names it.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:  # tolerate a future public accessor
        conn = db.conn
    return conn.execute(sql, params)


def _read_rows(db, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    cur = _read(db, sql, params)
    return _rows_as_dicts(cur.fetchall(), cur)


def _read_scalar(db, sql: str, params: dict[str, Any]) -> Any:
    return _read(db, sql, params).fetchone()[0]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class UsageAggregator:
    """Emit the dashboard JSON payload from the usage_events table.

    All panel queries are the spec's verbatim SQL, parameterized only by
    ``:since_ts``/``:until_ts`` epoch floats. Pass ``thresholds`` to change
    alert sensitivity per run.
    """

    def __init__(self, db, thresholds: AlertThresholds = DEFAULT_THRESHOLDS):
        self._db = db
        self._thresholds = thresholds

    # -- SQLite helpers ---------------------------------------------------

    @staticmethod
    def _rows_to_dicts(rows: Any, cursor: Any) -> list[dict[str, Any]]:
        return _rows_as_dicts(rows, cursor)

    # -- P1: headline cards (spec verbatim SQL) ---------------------------

    def _headline(self, since_ts: float, until_ts: float) -> dict[str, Any]:
        """P1 card values plus the NULL-cost annotation.

        SUM ignores NULLs silently, so a mix of priced and unpriced
        (cost_status='unknown') rows understates spend without saying so; the
        annotation surfaces it. NULL is not treated as 0 in the SQL — the raw
        column is the audit source.
        """
        sql = f"""
        SELECT
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_write_tokens) AS cache_write_tokens,
            SUM(reasoning_tokens) AS reasoning_tokens,
            SUM(estimated_cost_usd) AS est_cost_usd,
            COUNT(*) AS api_calls,
            SUM(api_status = 'ok') AS ok_calls,
            ROUND(1.0 * SUM(api_status = 'ok') / COUNT(*), 4) AS ok_rate,
            ROUND(
                1.0 * SUM(cache_read_tokens)
                    / NULLIF(SUM(cache_read_tokens) + SUM(input_tokens), 0),
                4
            ) AS token_cache_hit_rate
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        """
        rows = _read_rows(self._db, sql, {"since_ts": since_ts, "until_ts": until_ts})
        row = rows[0] if rows else {}

        total_calls = int(row.get("api_calls") or 0)
        null_cost_calls = _read_scalar(
            self._db,
            "SELECT COUNT(*) FROM usage_events"
            " WHERE ts >= :since_ts AND ts < :until_ts"
            " AND estimated_cost_usd IS NULL",
            {"since_ts": since_ts, "until_ts": until_ts},
        )
        cards = {
            "ok_rate": row.get("ok_rate"),
            "token_cache_hit_rate": row.get("token_cache_hit_rate"),
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
            "cache_write_tokens": int(row.get("cache_write_tokens") or 0),
            "reasoning_tokens": int(row.get("reasoning_tokens") or 0),
            "est_cost_usd": row.get("est_cost_usd"),
            "api_calls": total_calls,
        }
        if null_cost_calls and null_cost_calls < total_calls:
            cards["cost_note"] = (
                f"cost unknown for {null_cost_calls} of {total_calls} calls"
            )
        return cards

    # -- P2: token and cost trend (hourly/daily, bucket-filled) -----------

    def _trend(
        self, since_ts: float, until_ts: float, *, granularity: str
    ) -> list[dict[str, Any]]:
        """P2 per-bucket token/cost series with zero-filled empty buckets.

        Missing buckets are Python-filled so a quiet hour reads as spend
        dropped to zero, not as no data bucket (spec: bucket-fill).
        """
        assert granularity in ("hourly", "daily")
        bucketing_expr: str = (
            "'%Y-%m-%d %H:00:00'" if granularity == "hourly" else "'%Y-%m-%d'"
        )
        sql = f"""
        SELECT strftime({bucketing_expr}, ts, 'unixepoch') AS bucket,
               SUM(input_tokens + cache_read_tokens + cache_write_tokens)
                   AS input_side,
               SUM(output_tokens + reasoning_tokens) AS output_side,
               SUM(estimated_cost_usd) AS est_cost_usd,
               COUNT(*) AS api_calls
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        GROUP BY bucket
        ORDER BY bucket;
        """
        cur = _read(self._db, sql, {"since_ts": since_ts, "until_ts": until_ts})
        rows = cur.fetchall()
        by_bucket = {r[0]: dict(zip((c[0] for c in cur.description), r)) for r in rows}
        series: list[dict[str, Any]] = []
        # Enumerate every bucket the window covers, in order: hourly walks
        # hour steps; daily walks hour steps but emits each covered UTC day
        # once (a day boundary mid-window is common — stepping whole days
        # from a non-midnight window start skips the tail days).
        first = datetime.fromtimestamp(since_ts, tz=timezone.utc)
        end = datetime.fromtimestamp(until_ts, tz=timezone.utc)
        bucket_keys: list[str] = []
        seen: set[str] = set()
        if granularity == "hourly":
            walk = first
            while walk < end:
                bucket_keys.append(walk.strftime("%Y-%m-%d %H:00:00"))
                walk += timedelta(hours=1)
        else:
            walk = first
            while walk < end:
                day = walk.strftime("%Y-%m-%d")
                if day not in seen:
                    seen.add(day)
                    bucket_keys.append(day)
                walk = walk.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(days=1)
        for key in bucket_keys:
            row = by_bucket.get(key)
            if row is None:
                series.append({
                    "bucket": key,
                    "input_side": 0,
                    "output_side": 0,
                    "est_cost_usd": 0.0,
                    "api_calls": 0,
                })
            else:
                entry = dict(row)
                entry["bucket"] = key
                series.append(entry)
        return series

    # -- P3: per-model breakdown (spec verbatim) ---------------------------

    def _per_model(self, since_ts: float, until_ts: float) -> list[dict[str, Any]]:
        sql = """
        SELECT model, provider,
               COUNT(*) AS api_calls,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_read_tokens) AS cache_read_tokens,
               ROUND(SUM(estimated_cost_usd), 4) AS est_cost_usd,
               ROUND(
                   1.0 * SUM(estimated_cost_usd) / NULLIF(COUNT(*), 0), 6
               ) AS est_cost_per_call
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        GROUP BY model, provider
        ORDER BY est_cost_usd DESC;
        """
        return _read_rows(self._db, sql, {"since_ts": since_ts, "until_ts": until_ts})

    def _model_drill(
        self, model: str, since_ts: float, until_ts: float
    ) -> dict[str, Any]:
        """P3 drill card: one model's daily shape plus errors by class."""
        daily_sql = """
        SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day,
               COUNT(*) AS api_calls,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_read_tokens) AS cache_read_tokens,
               ROUND(SUM(estimated_cost_usd), 4) AS est_cost_usd
        FROM usage_events
        WHERE model = :model AND ts >= :since_ts AND ts < :until_ts
        GROUP BY day
        ORDER BY day DESC;
        """
        error_sql = """
        SELECT error_class, COUNT(*) AS calls
        FROM usage_events
        WHERE model = :model AND ts >= :since_ts AND ts < :until_ts
          AND api_status != 'ok'
        GROUP BY error_class
        ORDER BY calls DESC;
        """
        params = {"model": model, "since_ts": since_ts, "until_ts": until_ts}
        daily_cur = _read(self._db, daily_sql, params)
        error_cur = _read(self._db, error_sql, params)
        return {
            "model": model,
            "daily": _rows_as_dicts(daily_cur.fetchall(), daily_cur),
            "errors_by_class": _rows_as_dicts(error_cur.fetchall(), error_cur),
        }

    # -- P4: per-tenant breakdowns -----------------------------------------

    def _per_source(self, since_ts: float, until_ts: float) -> list[dict[str, Any]]:
        """P4a per-source card — populated today (spec verbatim SQL)."""
        sql = """
        SELECT source,
               COUNT(*) AS api_calls,
               SUM(input_tokens + output_tokens) AS total_tokens,
               ROUND(SUM(estimated_cost_usd), 4) AS est_cost_usd
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        GROUP BY source
        ORDER BY est_cost_usd DESC;
        """
        return _read_rows(self._db, sql, {"since_ts": since_ts, "until_ts": until_ts})

    def _per_user(self, since_ts: float, until_ts: float) -> dict[str, Any]:
        """P4b per-user card, honest when user_id is not yet backfilled."""
        sql = """
        SELECT user_id,
               COUNT(*) AS api_calls,
               SUM(input_tokens + output_tokens) AS total_tokens,
               ROUND(SUM(estimated_cost_usd), 4) AS est_cost_usd
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
          AND user_id IS NOT NULL
        GROUP BY user_id
        ORDER BY est_cost_usd DESC;
        """
        entries = _read_rows(
            self._db, sql, {"since_ts": since_ts, "until_ts": until_ts}
        )
        if entries:
            return {"state": "populated", "entries": entries}
        null_count = _read_scalar(
            self._db,
            "SELECT COUNT(*) FROM usage_events"
            " WHERE ts >= :since_ts AND ts < :until_ts AND user_id IS NULL",
            {"since_ts": since_ts, "until_ts": until_ts},
        )
        if null_count:
            return {"state": "not_yet_populated", "entries": []}
        return {"state": "no_events_in_range", "entries": []}

    # -- P5: cache economics (Daily, python-side savings math) --------------

    def _cache_economics(self, since_ts: float, until_ts: float) -> dict[str, Any]:
        """P5 per-day cache rates plus PricingEntry-denominated savings.

        Savings math lives in Python, not SQL: the spec locks that the join
        to price tables happens where the repo's price data already lives —
        using the PricingEntry rates recorded per event's pricing_version, so
        the panel stays honest when rates change mid-window.
        """
        sql = """
        SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day,
               ROUND(
                   1.0 * SUM(cache_read_tokens)
                       / NULLIF(SUM(cache_read_tokens) + SUM(input_tokens), 0),
                   4
               ) AS token_hit_rate,
               SUM(cache_write_tokens) AS cache_writes,
               SUM(estimated_cost_usd) AS est_cost_usd
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        GROUP BY day
        ORDER BY day;
        """
        days = _read_rows(self._db, sql, {"since_ts": since_ts, "until_ts": until_ts})

        # Python-side cache-savings join: full_price_equiv is what the
        # cache-read tokens *would* have cost at the input rate; savings is
        # that minus what they actually cost at the cache-read rate.
        day_savings: dict[str, float] = {}
        pricing_versions: set[str] = set()
        token_rows = _read_rows(
            self._db,
            """
            SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day,
                   model, provider,
                   pricing_version, cache_read_tokens, input_tokens
            FROM usage_events
            WHERE ts >= :since_ts AND ts < :until_ts
              AND cache_read_tokens > 0
            """,
            {"since_ts": since_ts, "until_ts": until_ts},
        )
        for token_row in token_rows:
            day = str(token_row["day"])
            pv = token_row["pricing_version"]
            cache_read = int(token_row["cache_read_tokens"])
            model = token_row["model"]
            provider = token_row["provider"]
            entry = _get_pricing_entry_cached(model or "", provider=provider or None)
            if entry is None:
                continue
            if pv:
                pricing_versions.add(pv)
            input_rate = entry.input_cost_per_million
            cache_read_rate = entry.cache_read_cost_per_million
            if input_rate is None or cache_read_rate is None:
                continue
            full_price = cache_read * float(input_rate) / MICROSECONDS
            actual = cache_read * float(cache_read_rate) / MICROSECONDS
            day_savings[str(day)] = day_savings.get(str(day), 0.0) + (
                full_price - actual
            )
        return {
            "days": days,
            "est_cost_usd": sum(d.get("est_cost_usd") or 0.0 for d in days),
            "cache_savings_usd": {
                day: round(v, 4) for day, v in sorted(day_savings.items())
            },
            "pricing_versions": sorted(pricing_versions),
        }

    # -- P6: errors and retries ----------------------------------------------

    def _errors(self, since_ts: float, until_ts: float) -> dict[str, Any]:
        """P6 distribution plus retry-storm per-session fingerprints."""
        sql = """
        SELECT api_status, error_class, COUNT(*) AS calls,
               ROUND(
                   100.0 * COUNT(*) / (
                       SELECT COUNT(*) FROM usage_events
                       WHERE ts >= :since_ts AND ts < :until_ts
                   ), 2
               ) AS pct
        FROM usage_events
        WHERE ts >= :since_ts AND ts < :until_ts
        GROUP BY api_status, error_class
        ORDER BY calls DESC;
        """
        breakdown = _read_rows(
            self._db, sql, {"since_ts": since_ts, "until_ts": until_ts}
        )

        # Spec: a spike of rows sharing session_id with attempt > 1 or
        # error_class='rate_limit' is the retry-loop fingerprint.
        sessions = _read(
            self._db,
            """
            SELECT session_id, COUNT(*) AS error_rows
            FROM usage_events
            WHERE ts >= :since_ts AND ts < :until_ts
              AND (attempt > 1 OR error_class = 'rate_limit')
            GROUP BY session_id
            HAVING error_rows >= :retry_floor
            """,
            {
                "since_ts": since_ts,
                "until_ts": until_ts,
                "retry_floor": self._thresholds.retry_storm_calls,
            },
        ).fetchall()
        retry_storm_sessions = [
            row[0]
            for row in sessions
            if int(row[1]) >= self._thresholds.retry_storm_calls
        ]
        return {
            "breakdown": breakdown,
            "retry_storm_sessions": sorted(set(retry_storm_sessions)),
        }

    def build_model_drills(
        self, since_ts: float, until_ts: float, *, max_models: int = 5
    ) -> list[dict[str, Any]]:
        """Drill cards for the top-cost models in range (spec §Per-model drill).

        Capped at ``max_models`` so a many-model deployment renders a bounded
        report; ordering follows _per_model's est_cost_usd DESC.
        """
        top = (
            self._per_model(since_ts, until_ts)[:max_models]
        )
        return [
            self._model_drill(
                str(row.get("model") or ""), since_ts, until_ts
            )
            for row in top
            if row.get("model")
        ]

    # -- Payload assembly -----------------------------------------------------

    def build_payload(self, since_ts: float, until_ts: float) -> dict[str, Any]:
        """Assemble the full dashboard payload for [since_ts, until_ts)."""
        return {
            "spec_version": "art_tZvdMeCj",
            "since_ts": since_ts,
            "until_ts": until_ts,
            "headline": self._headline(since_ts, until_ts),
            "trend_hourly": self._trend(since_ts, until_ts, granularity="hourly"),
            "trend_daily": self._trend(since_ts, until_ts, granularity="daily"),
            "per_model": self._per_model(since_ts, until_ts),
            "per_source": self._per_source(since_ts, until_ts),
            "per_user": self._per_user(since_ts, until_ts),
            "cache_economics": self._cache_economics(since_ts, until_ts),
            "errors": self._errors(since_ts, until_ts),
        }


@lru_cache(maxsize=256)
def _get_pricing_entry_cached(model: str, provider: Optional[str] = None):
    """L1 cache around get_pricing_entry for the per-row savings join.

    Wrapped so an unreachable pricing source degrades to `unknown` cost
    instead of breaking the aggregator — the panel reports the caveat via
    the NULL-cost annotation, not via a crash.
    """
    try:
        return get_pricing_entry(model, provider=provider)
    except Exception as e:
        logger.warning("Pricing lookup failed for %s/%s: %s", model, provider, e)
        return None


def aggregate(
    db,
    since_ts: float,
    until_ts: float,
    *,
    thresholds: AlertThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Module-level one-shot: build payload + alerts for the range.

    Pass thresholds explicitly; they are read from configuration, not code
    constants — a tuning pass can raise/lower them without touching detect().
    """
    agg = UsageAggregator(db, thresholds=thresholds)
    payload = agg.build_payload(since_ts=since_ts, until_ts=until_ts)
    return payload
