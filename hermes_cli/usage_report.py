"""``hermes usage-report`` CLI subcommand (spec art_tZvdMeCj, PR #4 of 4).

Reads the aggregator's payload (PR #3) and the detect() anomaly feed for a
time window, renders ONE static self-contained HTML report, and prints the
format_warning_line() summary. No always-on server, no alert routing — the
report file plus the printed warning are the entire round-1 delivery.

The report runs as a one-shot read against state.db (or --db-path), so it is
safe to run while the agent or gateway is live: SessionDB opens WAL, and this
process only reads.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.analytics.alerts import (
    alerts_payload,
    detect_from_db,
    format_warning_line,
)
from agent.analytics.aggregator import UsageAggregator
from agent.analytics.config import DEFAULT_THRESHOLDS
from agent.analytics.report import render_html
from hermes_state import SessionDB

# Default reporting window: the trailing 7 days, matching the spec's
# headline-card cadence (24h / 7d selectable; the full payload carries both
# granularities so the reader can slice either way).
DEFAULT_DAYS = 7


def _resolve_window(args: argparse.Namespace) -> tuple[float, float]:
    """Window [since_ts, until_ts) from --days/--since/--until epoch or ISO.

    Explicit --since/--until win; --days counts back from now (or from
    --until when given). Naive ISO timestamps are read as UTC — the
    aggregator's SQL buckets in UTC ('unixepoch'), so honoring local time
    here would silently shift every bucket boundary.
    """
    until_ts: float | None = None
    if args.until is not None:
        until_ts = _parse_ts_arg(args.until)
    since_ts: float | None = None
    if args.since is not None:
        since_ts = _parse_ts_arg(args.since)

    if until_ts is None:
        until_ts = datetime.now(timezone.utc).timestamp()
    if since_ts is None:
        since_ts = until_ts - args.days * 86400
    if since_ts >= until_ts:
        raise SystemExit(
            f"error: window is empty (since {since_ts} >= until {until_ts})"
        )
    return since_ts, until_ts


def _parse_ts_arg(raw: str) -> float:
    """Epoch seconds, or an ISO-8601 timestamp (naive = UTC, as bucketed)."""
    try:
        return float(raw)
    except ValueError:
        pass
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def build_report_payload(
    db: SessionDB, since_ts: float, until_ts: float
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """Aggregator payload + serialized anomaly feed + printed warning line."""
    aggregator = UsageAggregator(db, thresholds=DEFAULT_THRESHOLDS)
    payload = aggregator.build_payload(since_ts=since_ts, until_ts=until_ts)
    # Drill cards render per-model daily shapes for the top-cost models.
    payload["model_drills"] = aggregator.build_model_drills(since_ts, until_ts)
    # Anomaly feed: same window start, trailing-hour baseline per axis.
    alerts = detect_from_db(db, since_ts=since_ts, thresholds=DEFAULT_THRESHOLDS)
    return payload, alerts_payload(alerts), format_warning_line(alerts)


def write_report(
    db: SessionDB,
    since_ts: float,
    until_ts: float,
    output_path: Path,
) -> tuple[Path, str]:
    """Render and write the report file; returns (path, warning_line)."""
    payload, alert_dicts, warning_line = build_report_payload(db, since_ts, until_ts)
    html = render_html(payload, alert_dicts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path, warning_line


def run_usage_report(args: argparse.Namespace) -> int:
    """Entry point for the subcommand (wired via parser set_defaults)."""
    since_ts, until_ts = _resolve_window(args)
    db = SessionDB(db_path=Path(args.db_path) if args.db_path else None)
    try:
        if args.output:
            output_path = Path(args.output).expanduser()
        else:
            from hermes_constants import get_hermes_home

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            output_path = (
                get_hermes_home() / "reports" / f"usage-dashboard-{stamp}.html"
            )
        written, warning_line = write_report(db, since_ts, until_ts, output_path)
    finally:
        db.close()
    print(f"Usage report written to {written}")
    print(warning_line)
    return 0


def register_cli(parser: argparse.ArgumentParser) -> None:
    """Attach arguments to the already-created ``usage-report`` subparser.

    Follows the checkpoints-command pattern: main.py creates the subparser
    for help-text ordering and delegates flag registration here.
    """
    parser.add_argument(
        "-o",
        "--output",
        help="Output path for the HTML report (default: "
        "~/.hermes/reports/usage-dashboard-<timestamp>.html)",
    )
    parser.add_argument(
        "--db-path",
        help="Path to the state.db to read (default: the profile's state.db) — "
        "for test isolation and inspecting another deployment's data",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Window length in days, counted back from now or --until "
        f"(default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--since",
        help="Window start as epoch seconds or ISO-8601 (UTC); overrides --days",
    )
    parser.add_argument(
        "--until",
        help="Window end as epoch seconds or ISO-8601 (UTC); default: now",
    )


if __name__ == "__main__":  # pragma: no cover — direct debug invocation
    args = argparse.Namespace(
        output=None, db_path=None, days=DEFAULT_DAYS, since=None, until=None
    )
    sys.exit(run_usage_report(args))
