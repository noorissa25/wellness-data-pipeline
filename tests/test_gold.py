from __future__ import annotations

from datetime import date

import pytest

from conftest import load, walk, write_landing_file
from wellness import gold


def weather(d: str, high: float, condition: str = "clear", precip: float = 0):
    return {"weather_date": d, "temp_high_c": high, "temp_low_c": high - 5,
            "precip_mm": precip, "condition": condition}


@pytest.fixture
def built(con, landing):
    # Mon 2026-01-05 .. Sun 2026-01-18: two ISO weeks, with gaps on purpose.
    write_landing_file(landing, "walk_sessions", "w", [
        walk("a", "2026-01-05T07:00", 60, 5.0, steps="6500"),
        walk("b", "2026-01-05T18:00", 30, 2.5, steps="3300"),
        walk("c", "2026-01-10T09:00", 240, 20.0, steps="27000"),
        walk("d", "2026-01-18T09:00", 120, 10.0, steps="13500"),
    ])
    write_landing_file(landing, "daily_steps", "s", [
        {"activity_date": "2026-01-05", "steps": "12000", "source": "test"},
        {"activity_date": "2026-01-05", "steps": "11000", "source": "phone"},
        {"activity_date": "2026-01-10", "steps": "30000", "source": "test"},
        {"activity_date": "2026-01-12", "steps": "4000", "source": "test"},
    ])
    write_landing_file(landing, "weather", "x", [
        weather("2026-01-05", 2), weather("2026-01-10", -3, "snow", 4),
        weather("2026-01-12", 8, "rain", 6), weather("2026-01-18", 12),
    ])
    load(con, landing)
    gold.build(con)
    return con


def test_daily_activity_fills_every_calendar_day(built):
    rows = built.execute("SELECT count(*), min(activity_date), max(activity_date) "
                         "FROM gold.daily_activity").fetchone()
    assert rows == (14, date(2026, 1, 5), date(2026, 1, 18))
    quiet = built.execute("SELECT steps, walks, walk_km FROM gold.daily_activity "
                          "WHERE activity_date = '2026-01-07'").fetchone()
    assert quiet == (0, 0, 0)


def test_steps_take_the_highest_device_not_the_sum(built):
    assert built.execute("SELECT steps FROM gold.daily_activity "
                         "WHERE activity_date = '2026-01-05'").fetchone()[0] == 12000


def test_steps_fall_back_to_walk_steps(built):
    assert built.execute("SELECT steps FROM gold.daily_activity "
                         "WHERE activity_date = '2026-01-18'").fetchone()[0] == 13500


def test_weekly_totals(built):
    rows = built.execute(
        "SELECT week_start, walks, total_km, total_hours, longest_walk_km, active_days, "
        "days_over_10k_steps FROM gold.weekly_walking ORDER BY 1").fetchall()
    assert rows == [
        (date(2026, 1, 5), 3, 27.5, 5.5, 20.0, 2, 2),
        (date(2026, 1, 12), 1, 10.0, 2.0, 10.0, 1, 1),
    ]


def test_longest_walks_ranked_by_distance(built):
    rows = built.execute("SELECT rank_by_distance, session_id, condition "
                         "FROM gold.longest_walks").fetchall()
    assert rows == [(1, "c", "snow"), (2, "d", "clear"), (3, "a", "clear"), (4, "b", "clear")]


def test_walking_vs_weather(built):
    rows = {(d, b): (days, walk_days, km) for d, b, days, walk_days, km in built.execute(
        "SELECT dimension, bucket, days, walk_days, avg_km_per_day FROM gold.walking_vs_weather"
    ).fetchall()}
    assert rows[("condition", "clear")] == (2, 2, pytest.approx(8.75))
    assert rows[("condition", "rain")] == (1, 0, 0)
    assert rows[("temperature", "below 0 °C")] == (1, 1, 20.0)
    # only the 4 days with weather are bucketed, once per dimension
    assert sum(v[0] for k, v in rows.items() if k[0] == "temperature") == 4


def test_rebuild_is_idempotent(built):
    before = built.execute("SELECT * FROM gold.weekly_walking ORDER BY 1").fetchall()
    gold.build(built)
    assert built.execute("SELECT * FROM gold.weekly_walking ORDER BY 1").fetchall() == before
