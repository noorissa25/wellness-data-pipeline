from __future__ import annotations

import pytest

from conftest import load, walk, write_landing_file
from wellness import quality


def test_failed_error_check_raises_and_is_recorded(con):
    checks = (
        quality.Check("silver", "always_fails", "error", "demo", "SELECT 3"),
        quality.Check("silver", "always_passes", "error", "demo", "SELECT 0"),
    )
    with pytest.raises(quality.DataQualityError, match=r"always_fails \(3\)"):
        quality.run_checks(con, 1, checks)
    assert con.execute("SELECT check_name, passed, failed_rows FROM meta.dq_results "
                       "ORDER BY 1").fetchall() == [("always_fails", False, 3),
                                                    ("always_passes", True, 0)]


def test_warn_check_does_not_raise(con):
    checks = (quality.Check("gold", "soft", "warn", "demo", "SELECT 1"),)
    [result] = quality.run_checks(con, 1, checks)
    assert result["passed"] is False


def test_high_quarantine_rate_fails_the_run(con, landing):
    rows = [walk(f"w{i}", "2026-01-01T08:00", 60, 5) for i in range(10)]
    for r in rows[:2]:
        r["start_time"] = "garbage"
    write_landing_file(landing, "walk_sessions", "a", rows)
    load(con, landing)
    results = quality.evaluate(con, quality.SILVER_CHECKS)
    rate = next(r for r in results if r["check"].name == "quarantine_rate_below_5pct")
    assert rate["failed_rows"] == 1
    with pytest.raises(quality.DataQualityError, match="quarantine_rate"):
        quality.raise_on_errors(results)


def test_overlapping_sessions_are_flagged(con, landing):
    write_landing_file(landing, "walk_sessions", "a", [
        walk("w1", "2026-01-01T08:00", 60, 5),
        walk("w2", "2026-01-01T08:30", 60, 5),
    ])
    load(con, landing)
    results = {r["check"].name: r for r in quality.evaluate(con, quality.SILVER_CHECKS)}
    assert results["no_sessions_overlap"]["failed_rows"] == 1
