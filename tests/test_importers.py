from __future__ import annotations

import csv

import pytest

from conftest import FIXTURES, load
from wellness import importers


def read(path):
    with path.open() as fh:
        return list(csv.DictReader(fh))


def test_google_fit_daily(landing):
    [out] = importers.import_export(
        "google-fit-daily", FIXTURES / "google_fit_daily_activity_metrics.csv", landing)
    assert out.parent.name == "daily_steps"
    assert read(out) == [
        {"activity_date": "2026-02-01", "steps": "10210", "source": "google_fit"},
        {"activity_date": "2026-02-02", "steps": "4402", "source": "google_fit"},
    ]


def test_apple_health_records_sum_steps_per_day(landing):
    [out] = importers.import_export(
        "apple-health-records", FIXTURES / "apple_health_records.csv", landing)
    assert [(r["activity_date"], r["steps"]) for r in read(out)] == [
        ("2026-02-01", "6000"), ("2026-02-02", "5005")]


def test_apple_health_workouts_keep_walks_and_convert_units(landing):
    [out] = importers.import_export(
        "apple-health-workouts", FIXTURES / "apple_health_workouts.csv", landing)
    rows = read(out)
    assert len(rows) == 2  # the run is dropped
    walk, hike = rows
    assert (walk["start_time"], walk["end_time"], walk["duration_min"], walk["distance_km"]) == (
        "2026-02-01T08:00", "2026-02-01T09:12", "72.5", "6.4")
    assert hike["duration_min"] == "186.0"
    assert float(hike["distance_km"]) == pytest.approx(13.197, abs=0.001)
    assert walk["session_id"].startswith("ah-") and walk["session_id"] != hike["session_id"]


def test_imported_files_flow_through_silver(con, landing):
    for fmt, name in [("google-fit-daily", "google_fit_daily_activity_metrics.csv"),
                      ("apple-health-records", "apple_health_records.csv"),
                      ("apple-health-workouts", "apple_health_workouts.csv")]:
        importers.import_export(fmt, FIXTURES / name, landing)
    _, res = load(con, landing)
    assert res["walk_sessions"].upserted == 2
    assert res["daily_steps"].upserted == 4
    assert con.execute("SELECT count(*) FROM silver.quarantine").fetchone()[0] == 0


def test_unknown_format(landing):
    with pytest.raises(ValueError, match="unknown format"):
        importers.import_export("fitbit", FIXTURES / "apple_health_records.csv", landing)
