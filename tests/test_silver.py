from __future__ import annotations

from datetime import date

from conftest import load, walk, write_landing_file


def test_types_are_enforced(con, landing):
    write_landing_file(landing, "walk_sessions", "a",
                       [walk("w1", "2026-01-01T08:00", 60, 5.0, steps="6800")])
    load(con, landing)
    row = con.execute(
        "SELECT walk_date, distance_km, steps, pace_min_per_km FROM silver.walk_sessions"
    ).fetchone()
    assert row == (date(2026, 1, 1), 5.0, 6800, 12.0)


def test_bad_rows_are_quarantined_with_a_reason(con, landing):
    good = walk("ok", "2026-01-01T08:00", 60, 5)
    negative = walk("neg", "2026-01-02T08:00", 60, -5)
    reversed_ = walk("rev", "2026-01-03T08:00", 60, 5)
    reversed_["start_time"], reversed_["end_time"] = reversed_["end_time"], reversed_["start_time"]
    unparseable = walk("na", "2026-01-04T08:00", 60, 5)
    unparseable["start_time"] = "N/A"
    too_fast = walk("fast", "2026-01-05T08:00", 10, 5)  # 2 min/km is not a walk
    write_landing_file(landing, "walk_sessions", "a",
                       [good, negative, reversed_, unparseable, too_fast])
    _, res = load(con, landing)

    assert res["walk_sessions"].quarantined == 4
    assert con.execute("SELECT list(session_id) FROM silver.walk_sessions").fetchone()[0] == ["ok"]
    reasons = dict(con.execute(
        "SELECT record->>'session_id', reason FROM silver.quarantine").fetchall())
    assert reasons == {
        "neg": "distance_km missing or out of range [0.1, 80]",
        "rev": "end_time not after start_time",
        "na": "unparseable start_time",
        "fast": "pace outside walking range [6, 30] min/km",
    }


def test_duplicates_within_a_file_collapse(con, landing):
    w = walk("w1", "2026-01-01T08:00", 60, 5)
    write_landing_file(landing, "walk_sessions", "a", [w, w, w])
    _, res = load(con, landing)
    assert (res["walk_sessions"].upserted, res["walk_sessions"].duplicates) == (1, 2)


def test_newest_batch_wins_on_overlap(con, landing):
    write_landing_file(landing, "daily_steps", "1_first", [
        {"activity_date": "2026-01-01", "steps": "8000", "source": "watch"},
        {"activity_date": "2026-01-02", "steps": "9000", "source": "watch"},
    ])
    write_landing_file(landing, "daily_steps", "2_resync", [
        {"activity_date": "2026-01-02", "steps": "9500", "source": "watch"},
        {"activity_date": "2026-01-03", "steps": "7000", "source": "watch"},
    ])
    load(con, landing)
    rows = con.execute(
        "SELECT activity_date::VARCHAR, steps FROM silver.daily_steps ORDER BY 1").fetchall()
    assert rows == [("2026-01-01", 8000), ("2026-01-02", 9500), ("2026-01-03", 7000)]


def test_incremental_load_only_reads_new_batches(con, landing):
    write_landing_file(landing, "weather", "1", [
        {"weather_date": "2026-01-01", "temp_high_c": "5", "temp_low_c": "0",
         "precip_mm": "0", "condition": "clear"}])
    _, first = load(con, landing)
    _, again = load(con, landing)
    assert first["weather"].read == 1
    assert again["weather"].read == 0

    write_landing_file(landing, "weather", "2", [
        {"weather_date": "2026-01-01", "temp_high_c": "6", "temp_low_c": "0",
         "precip_mm": "2", "condition": "Rain"},
        {"weather_date": "2026-01-02", "temp_high_c": "4", "temp_low_c": "-1",
         "precip_mm": "0", "condition": "overcast"}])
    _, later = load(con, landing)
    assert later["weather"].read == 2
    assert con.execute("SELECT count(*), max(temp_high_c) FROM silver.weather").fetchone() == (2, 6)
    # values are normalised as well as typed
    assert con.execute("SELECT condition FROM silver.weather WHERE weather_date = '2026-01-01'"
                       ).fetchone()[0] == "rain"


def test_invalid_newer_row_does_not_replace_valid_older_row(con, landing):
    write_landing_file(landing, "walk_sessions", "1", [walk("w1", "2026-01-01T08:00", 60, 5)])
    bad = walk("w1", "2026-01-01T08:00", 60, 500)
    write_landing_file(landing, "walk_sessions", "2", [bad])
    load(con, landing)
    assert con.execute("SELECT distance_km FROM silver.walk_sessions").fetchone()[0] == 5
    assert con.execute("SELECT count(*) FROM silver.quarantine").fetchone()[0] == 1
