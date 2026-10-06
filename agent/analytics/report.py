"""Static HTML report renderer for the token-usage dashboard (spec art_tZvdMeCj).

Round-1 delivery is one generated HTML file per run: a single CLI command
builds the aggregator's payload (PR #3), runs detect() for the anomaly feed,
and renders one self-contained HTML file — no always-on server, no new
frontend framework, no template-engine dependency (the emitter is pure
Python with an html-escape in front of every dynamic value).

Every number on the page re-derivable by running the spec's verbatim SQL
against the same state.db and window; the complete payload is embedded as a
JSON blob so the report doubles as the reproducibility record.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

SEVERITY_CLASS = {"critical": "crit", "warning": "warn", "info": "info"}


def _fmt_num(value: Any) -> str:
    """Integer-ish display for token/call counts; em dash for None."""
    if value is None:
        return "—"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{n:,}"


def _fmt_cost(value: Any) -> str:
    """USD display with 4 decimals; em dash for NULL (never silently $0)."""
    if value is None:
        return "—"
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_rate(value: Any) -> str:
    """0..1 fraction to percent, em dash for None (e.g. zero-event windows)."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "—")


def _table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    """Escape-everything table builder. Empty body renders an honest empty row."""
    body = [
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
        for row in rows
    ]
    if not body:
        ncols = len(headers)
        body = [f'<tr><td colspan="{ncols}" class="empty">no events in range</td></tr>']
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{_esc(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _p1_headline(payload: Mapping[str, Any]) -> str:
    """Headline cards (P1) + the NULL-cost annotation when present."""
    h = payload.get("headline") or {}
    note = h.get("cost_note")
    note_html = (
        f'<p class="note">{_esc(note)}</p>' if note else ""
    )
    cards = [
        ("Input tokens", _fmt_num(h.get("input_tokens"))),
        ("Output tokens", _fmt_num(h.get("output_tokens"))),
        ("Cache read", _fmt_num(h.get("cache_read_tokens"))),
        ("Cache write", _fmt_num(h.get("cache_write_tokens"))),
        ("Reasoning", _fmt_num(h.get("reasoning_tokens"))),
        ("Est. cost", _fmt_cost(h.get("est_cost_usd"))),
        ("API calls", _fmt_num(h.get("api_calls"))),
        ("OK rate", _fmt_rate(h.get("ok_rate"))),
        ("Cache hit rate", _fmt_rate(h.get("token_cache_hit_rate"))),
    ]
    card_html = "".join(
        f'<div class="card"><div class="card-label">{_esc(label)}</div>'
        f'<div class="card-value">{value}</div></div>'
        for label, value in cards
    )
    return f'<section id="p1"><h2>Headline</h2>{note_html}<div class="cards">{card_html}</div></section>'


def _p2_trend(payload: Mapping[str, Any], granularity: str) -> str:
    """Zero-filled hourly/daily trend table (P2). Quiet buckets render as 0."""
    key = "trend_hourly" if granularity == "hourly" else "trend_daily"
    rows = [
        (
            r.get("bucket", "—"),
            _fmt_num(r.get("input_side")),
            _fmt_num(r.get("output_side")),
            _fmt_cost(r.get("est_cost_usd")),
            _fmt_num(r.get("api_calls")),
        )
        for r in payload.get(key) or []
    ]
    return _table(["Bucket", "Input-side tokens", "Output-side tokens", "Est. cost", "API calls"], rows)


def _p3_models(payload: Mapping[str, Any]) -> str:
    rows = [
        (
            r.get("model") or "unknown",
            r.get("provider") or "—",
            _fmt_num(r.get("api_calls")),
            _fmt_num(r.get("input_tokens")),
            _fmt_num(r.get("output_tokens")),
            _fmt_num(r.get("cache_read_tokens")),
            _fmt_cost(r.get("est_cost_usd")),
            _fmt_cost(r.get("est_cost_per_call")),
        )
        for r in payload.get("per_model") or []
    ]
    return _table(
        ["Model", "Provider", "API calls", "Input", "Output", "Cache read", "Est. cost", "Cost/call"],
        rows,
    )


def _p4_tenant(payload: Mapping[str, Any]) -> str:
    """P4a per-source table (always real) + P4b per-user honesty state."""
    source_rows = [
        (
            r.get("source") or "unknown",
            _fmt_num(r.get("api_calls")),
            _fmt_num(r.get("total_tokens")),
            _fmt_cost(r.get("est_cost_usd")),
        )
        for r in payload.get("per_source") or []
    ]
    source_html = _table(
        ["Source", "API calls", "Total tokens", "Est. cost"], source_rows
    )

    per_user = payload.get("per_user") or {}
    state = per_user.get("state", "no_events_in_range")
    if state == "populated":
        user_rows = [
            (
                r.get("user_id") or "unknown",
                _fmt_num(r.get("api_calls")),
                _fmt_num(r.get("total_tokens")),
                _fmt_cost(r.get("est_cost_usd")),
            )
            for r in per_user.get("entries") or []
        ]
        user_html = _table(["User", "API calls", "Total tokens", "Est. cost"], user_rows)
    elif state == "not_yet_populated":
        # Spec §P4b: render the honest placeholder, not a fake empty table.
        user_html = '<p class="empty-state">user attribution not yet populated (user_id backfill pending)</p>'
    else:
        user_html = '<p class="empty-state">no events in range</p>'
    return source_html + "<h3>By user</h3>" + user_html


def _cache_economics(payload: Mapping[str, Any]) -> str:
    ce = payload.get("cache_economics") or {}
    rows = [
        (
            d.get("day", "—"),
            _fmt_rate(d.get("token_hit_rate")),
            _fmt_num(d.get("cache_writes")),
            _fmt_cost(d.get("est_cost_usd")),
            _fmt_cost(ce.get("cache_savings_usd", {}).get(d.get("day"))),
        )
        for d in ce.get("days") or []
    ]
    versions = ", ".join(ce.get("pricing_versions") or []) or "—"
    return (
        _table(
            ["Day", "Cache hit rate", "Cache writes", "Est. cost", "Cache savings"],
            rows,
        )
        + f'<p class="note">pricing versions: {_esc(versions)}</p>'
    )


def _model_drills(payload: Mapping[str, Any]) -> str:
    """Per-model drill cards: daily shape + errors by class."""
    drills = payload.get("model_drills") or []
    if not drills:
        return '<p class="empty-state">no drill data — no models with events in range</p>'
    out = []
    for d in drills:
        daily_rows = [
            (
                r.get("day", "—"),
                _fmt_num(r.get("api_calls")),
                _fmt_num(r.get("input_tokens")),
                _fmt_num(r.get("output_tokens")),
                _fmt_cost(r.get("est_cost_usd")),
            )
            for r in d.get("daily") or []
        ]
        err_rows = [
            (r.get("error_class") or "unclassified", _fmt_num(r.get("calls")))
            for r in d.get("errors_by_class") or []
        ]
        head = f"<h3>{_esc(d.get('model', 'unknown'))}</h3>"
        out.append(
            head
            + _table(
                ["Day", "API calls", "Input", "Output", "Est. cost"], daily_rows
            )
            + "<h4>Errors by class</h4>"
            + _table(["Error class", "Calls"], err_rows)
        )
    return "".join(f'<section class="drill">{x}</section>' for x in out)


def _anomaly_feed(alert_dicts: list[dict[str, str]]) -> str:
    """Anomaly feed table from detect() output (round-1 delivery surface)."""
    body = [
        f'<tr class="alert-{_esc(SEVERITY_CLASS.get(sev, sev))}">'
        + "".join(f"<td>{_esc(c)}</td>" for c in (sev, axis, bucket, msg))
        + "</tr>"
        for sev, axis, bucket, msg in (
            (a.get("severity", "?"), a.get("axis", "?"),
             a.get("bucket", "?"), a.get("message", ""))
            for a in alert_dicts
        )
    ]
    if not body:
        body = ['<tr><td colspan="4" class="empty">no anomalies detected</td></tr>']
    return (
        "<table><thead><tr><th>Severity</th><th>Axis</th><th>Hour</th>"
        "<th>Detail</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_html(
    payload: Mapping[str, Any],
    alerts: Iterable[Mapping[str, str]] = (),
    *,
    opened_at_iso: str | None = None,
) -> str:
    """Render one self-contained HTML report from the aggregator payload.

    ``payload`` is :meth:`UsageAggregator.build_payload` output (PR #3),
    optionally extended with ``model_drills`` by :func:`build_drills`.
    ``alerts`` is serialized detect() output (Alert.as_dict() dicts).
    The full payload is embedded as a JSON blob (``</`` escaped so it is
    safe inside a <script> tag) for auditability.
    """
    opened_at_iso = opened_at_iso or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    alert_dicts = [dict(a) for a in alerts]
    payload_doc: dict[str, Any] = dict(payload)

    p2_hourly = _p2_trend(payload, "hourly")
    p2_daily = _p2_trend(payload, "daily")
    embed_json = json.dumps(payload_doc, sort_keys=True, default=str).replace(
        "</", "<\\/"
    )

    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>Hermes Token Usage Analytics</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a1a;max-width:1100px}",
        "h2{border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:2rem}",
        "table{border-collapse:collapse;width:100%;margin:0.5rem 0;font-size:0.9rem}",
        "th,td{border:1px solid #ddd;padding:4px 8px;text-align:left}",
        "th{background:#f5f5f5}",
        ".cards{display:flex;flex-wrap:wrap;gap:12px}",
        ".card{border:1px solid #ddd;border-radius:8px;padding:10px 16px;min-width:130px}",
        ".card-label{font-size:0.75rem;color:#666;text-transform:uppercase}",
        ".card-value{font-size:1.25rem;font-weight:600}",
        ".note{color:#8a6d3b;font-size:0.85rem}",
        ".empty{color:#999;font-style:italic}",
        ".empty-state{color:#777;font-style:italic;border:1px dashed #ccc;padding:8px;background:#fafafa}",
        ".alert-crit td:first-child{background:#fdd}",
        ".alert-warn td:first-child{background:#fec}",
        ".alert-info td:first-child{background:#eef}",
        ".drill{border-left:3px solid #ccc;padding-left:12px;margin-bottom:1rem}",
        "</style></head><body>",
        "<h1>Hermes Token Usage Analytics</h1>",
        f"<p>Window: {_esc(_fmt_ts(payload.get('since_ts')))} → {_esc(_fmt_ts(payload.get('until_ts')))}"
        f" · generated {opened_at_iso} · spec {payload_doc.get('spec_version', 'art_tZvdMeCj')}</p>",
        _p1_headline(payload),
        "<section id='p2-hourly'><h2>Hourly Trend</h2>" + p2_hourly + "</section>",
        "<section id='p2-daily'><h2>Daily Trend</h2>" + p2_daily + "</section>",
        "<section id='p3-models'><h2>Per-Model</h2>" + _p3_models(payload) + "</section>",
        "<section id='p4-tenant'><h2>Per-Tenant</h2>"
        "<h3>By source</h3>" + _p4_tenant(payload) + "</section>",
        "<section id='p5-cache'><h2>Cache Economics</h2>" + _cache_economics(payload) + "</section>",
        "<section id='p6-errors'><h2>Errors & Retries</h2>" + _errors_section(payload) + "</section>",
        "<section id='anomalies'><h2>Anomaly Feed</h2>" + _anomaly_feed(alert_dicts) + "</section>",
        "<section id='drills'><h2>Per-Model Drill</h2>" + _model_drills(payload) + "</section>",
        "<details><summary>Embedded payload (audit)</summary>"
        f"<pre id='payload-json'>{_esc(embed_json)}</pre></details>",
        "</body></html>",
    ]
    return "\n".join(parts)


def _fmt_ts(ts: Any) -> str:
    """epoch float to UTC ISO string, verbatim-transparent for None."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M %Z"
        )
    except (TypeError, ValueError):
        return "—"


def _errors_section(payload: Mapping[str, Any]) -> str:
    err = payload.get("errors") or {}
    rows = [
        (
            r.get("api_status") or "unknown",
            r.get("error_class") or "unclassified",
            _fmt_num(r.get("calls")),
            f"{r.get('pct', 0)}%",
        )
        for r in err.get("breakdown") or []
    ]
    table = _table(["API status", "Error class", "Calls", "%"], rows)
    storms = err.get("retry_storm_sessions") or []
    if storms:
        listing = ", ".join(_esc(s) for s in storms)
        storm_html = f'<p class="note">retry-storm sessions (≥ threshold rows): {listing}</p>'
    else:
        storm_html = '<p class="empty">no retry-storm fingerprints in range</p>'
    return table + storm_html
