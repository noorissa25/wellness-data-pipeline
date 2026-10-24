"""Publish the gold layer as a static, self-contained web page (for GitHub Pages).

The Streamlit dashboard needs a Python server; this page does not. It embeds the gold
and meta tables as JSON in one HTML file, and a small script in the page computes the
same summaries for whichever date range the viewer picks. No external scripts, so it
loads quickly on a phone and keeps working offline once opened.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from wellness.labels import CHECKS, REASONS

TEMPLATE = Path(__file__).with_name("site_template.html")
PLACEHOLDER = "/*__DATA__*/null"


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[list]:
    return [list(r) for r in con.execute(sql).fetchall()]


def collect(con: duckdb.DuckDBPyConnection) -> dict:
    """Everything the page needs, as plain JSON-serialisable values."""
    daily = _rows(con, """
        SELECT strftime(activity_date, '%Y-%m-%d'), steps, walks, round(walk_km, 3),
               round(walk_minutes, 1), round(longest_walk_km, 3), temp_high_c, condition
        FROM gold.daily_activity ORDER BY activity_date""")
    walks = _rows(con, """
        SELECT strftime(w.walk_date, '%Y-%m-%d'), round(w.distance_km, 3), w.duration_min,
               w.pace_min_per_km, x.condition, x.temp_high_c
        FROM silver.walk_sessions w LEFT JOIN silver.weather x ON x.weather_date = w.walk_date
        ORDER BY w.distance_km DESC, w.start_ts""")
    checks = []
    for layer, name, severity, passed, failed in _rows(con, """
            SELECT layer, check_name, severity, passed, failed_rows FROM meta.dq_results
            WHERE run_id = (SELECT max(run_id) FROM meta.dq_results)
            ORDER BY layer DESC, check_name"""):
        title, desc = CHECKS.get(name, (name.replace("_", " ").capitalize(), ""))
        checks.append({"layer": layer, "title": title, "desc": desc, "severity": severity,
                       "passed": bool(passed), "failed": int(failed)})
    quarantine = [{"reason": REASONS.get(r, r.capitalize()), "n": n} for r, n in _rows(con, """
        SELECT reason, count(*) FROM silver.quarantine GROUP BY 1 ORDER BY 2 DESC""")]
    files, raw_rows = con.execute(
        "SELECT count(*), coalesce(sum(row_count), 0) FROM meta.ingested_files").fetchone()
    # Dates only: run times are in the building machine's local time zone.
    last_run = con.execute(
        "SELECT strftime(finished_at, '%Y-%m-%d') FROM meta.runs "
        "WHERE status = 'succeeded' ORDER BY run_id DESC LIMIT 1").fetchone()
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "daily": daily,
        "walks": walks,
        "checks": checks,
        "quarantine": quarantine,
        "files": int(files),
        "rawRows": int(raw_rows),
        "lastRun": last_run[0] if last_run else None,
    }


def render(data: dict) -> str:
    # "</" is escaped so no value can close the <script> element early.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"{TEMPLATE.name} is missing the {PLACEHOLDER!r} placeholder")
    return template.replace(PLACEHOLDER, payload)


def export_site(con: duckdb.DuckDBPyConnection, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render(collect(con)), encoding="utf-8")
    (out_dir / ".nojekyll").touch()  # serve files as-is on GitHub Pages
    return index
