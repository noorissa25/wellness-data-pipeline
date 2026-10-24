from __future__ import annotations

import pytest

from conftest import walk, write_landing_file
from wellness import bronze
from wellness.config import DATASETS


def test_ingests_raw_strings_with_lineage(con, landing):
    write_landing_file(landing, "walk_sessions", "a", [walk("w1", "2026-01-01T08:00", 60, 5)])
    [f] = bronze.ingest_landing(con, landing)
    assert (f.dataset, f.batch_id, f.rows) == ("walk_sessions", 1, 1)
    row = con.execute(
        "SELECT distance_km, _batch_id, _source_file, _row_number FROM bronze.walk_sessions"
    ).fetchone()
    assert row == ("5", 1, "a.csv", 1)


def test_same_file_is_ingested_once(con, landing):
    write_landing_file(landing, "weather", "w", [{"weather_date": "2026-01-01"}])
    assert len(bronze.ingest_landing(con, landing)) == 1
    assert bronze.ingest_landing(con, landing) == []
    assert con.execute("SELECT count(*) FROM bronze.weather").fetchone()[0] == 1


def test_identical_content_under_new_name_is_skipped(con, landing):
    rows = [{"activity_date": "2026-01-01", "steps": "100", "source": "x"}]
    write_landing_file(landing, "daily_steps", "first", rows)
    bronze.ingest_landing(con, landing)
    write_landing_file(landing, "daily_steps", "renamed_copy", rows)
    assert bronze.ingest_landing(con, landing) == []


def test_each_new_file_gets_the_next_batch(con, landing):
    write_landing_file(landing, "weather", "a", [{"weather_date": "2026-01-01"}])
    bronze.ingest_landing(con, landing)
    write_landing_file(landing, "weather", "b", [{"weather_date": "2026-01-02"}])
    [f] = bronze.ingest_landing(con, landing)
    assert f.batch_id == 2


def test_missing_column_breaks_the_contract(con, landing):
    path = landing / "weather" / "bad.csv"
    path.parent.mkdir(parents=True)
    path.write_text("weather_date,temp_high_c\n2026-01-01,10\n")
    with pytest.raises(bronze.SchemaContractError, match="temp_low_c"):
        bronze.ingest_file(con, DATASETS["weather"], path)


def test_extra_columns_are_ignored(con, landing):
    path = landing / "daily_steps" / "extra.csv"
    path.parent.mkdir(parents=True)
    path.write_text("activity_date,steps,source,heart_points\n2026-01-01,500,x,12\n")
    bronze.ingest_landing(con, landing)
    cols = [r[0] for r in con.execute("DESCRIBE bronze.daily_steps").fetchall()]
    assert "heart_points" not in cols
