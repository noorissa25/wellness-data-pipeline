"""Silver: typed, validated, deduplicated tables, loaded incrementally from bronze.

For each dataset, silver reads only bronze batches newer than its watermark, then:

1. enforces the schema by casting every column with TRY_CAST (bad values become NULL),
2. applies row rules; a row that breaks one goes to ``silver.quarantine`` with the reason,
3. deduplicates on the business key, keeping the row from the newest batch,
4. upserts into the silver table (``INSERT OR REPLACE`` on the primary key),
5. moves the watermark forward, all in one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from wellness.config import DATASETS
from wellness.warehouse import scalar


@dataclass(frozen=True)
class SilverSpec:
    ddl: str
    typed: str  # SELECT over bronze, with typed columns plus lineage
    rules: tuple[tuple[str, str], ...]  # (reason, SQL predicate that is TRUE for a bad row)
    columns: tuple[str, ...]  # silver columns, in DDL order, excluding _batch_id/_updated_at
    project: str  # expressions producing `columns` from the typed row


SPECS: dict[str, SilverSpec] = {
    "walk_sessions": SilverSpec(
        ddl="""
            CREATE TABLE IF NOT EXISTS silver.walk_sessions (
                session_id       VARCHAR PRIMARY KEY,
                walk_date        DATE NOT NULL,
                start_ts         TIMESTAMP NOT NULL,
                end_ts           TIMESTAMP NOT NULL,
                duration_min     DOUBLE NOT NULL,
                distance_km      DOUBLE NOT NULL,
                steps            INTEGER,
                pace_min_per_km  DOUBLE NOT NULL,
                source           VARCHAR NOT NULL,
                _batch_id        INTEGER NOT NULL,
                _updated_at      TIMESTAMP NOT NULL
            )""",
        typed="""
            SELECT nullif(session_id, '')                 AS session_id,
                   TRY_CAST(start_time AS TIMESTAMP)      AS start_ts,
                   TRY_CAST(end_time AS TIMESTAMP)        AS end_ts,
                   TRY_CAST(duration_min AS DOUBLE)       AS duration_min,
                   TRY_CAST(distance_km AS DOUBLE)        AS distance_km,
                   TRY_CAST(nullif(steps, '') AS INTEGER) AS steps,
                   lower(nullif(source, ''))              AS source,
                   _batch_id, _row_number
            FROM bronze.walk_sessions""",
        rules=(
            ("missing session_id", "session_id IS NULL"),
            ("unparseable start_time", "start_ts IS NULL"),
            ("unparseable end_time", "end_ts IS NULL"),
            ("end_time not after start_time", "end_ts <= start_ts"),
            ("duration_min missing or not positive", "coalesce(duration_min, 0) <= 0"),
            ("distance_km missing or out of range [0.1, 80]",
             "distance_km IS NULL OR distance_km < 0.1 OR distance_km > 80"),
            ("pace outside walking range [6, 30] min/km",
             "duration_min / distance_km NOT BETWEEN 6 AND 30"),
            ("negative steps", "steps < 0"),
            ("missing source", "source IS NULL"),
        ),
        columns=("session_id", "walk_date", "start_ts", "end_ts", "duration_min", "distance_km",
                 "steps", "pace_min_per_km", "source"),
        project="""session_id, CAST(start_ts AS DATE), start_ts, end_ts, duration_min,
                   distance_km, steps, round(duration_min / distance_km, 2), source""",
    ),
    "daily_steps": SilverSpec(
        ddl="""
            CREATE TABLE IF NOT EXISTS silver.daily_steps (
                activity_date  DATE NOT NULL,
                source         VARCHAR NOT NULL,
                steps          INTEGER NOT NULL,
                _batch_id      INTEGER NOT NULL,
                _updated_at    TIMESTAMP NOT NULL,
                PRIMARY KEY (activity_date, source)
            )""",
        typed="""
            SELECT TRY_CAST(activity_date AS DATE)      AS activity_date,
                   lower(nullif(source, ''))            AS source,
                   TRY_CAST(TRY_CAST(steps AS DOUBLE) AS INTEGER) AS steps,
                   _batch_id, _row_number
            FROM bronze.daily_steps""",
        rules=(
            ("unparseable activity_date", "activity_date IS NULL"),
            ("missing source", "source IS NULL"),
            ("steps missing or out of range [0, 150000]",
             "steps IS NULL OR steps < 0 OR steps > 150000"),
        ),
        columns=("activity_date", "source", "steps"),
        project="activity_date, source, steps",
    ),
    "weather": SilverSpec(
        ddl="""
            CREATE TABLE IF NOT EXISTS silver.weather (
                weather_date  DATE PRIMARY KEY,
                temp_high_c   DOUBLE NOT NULL,
                temp_low_c    DOUBLE NOT NULL,
                precip_mm     DOUBLE NOT NULL,
                condition     VARCHAR NOT NULL,
                _batch_id     INTEGER NOT NULL,
                _updated_at   TIMESTAMP NOT NULL
            )""",
        typed="""
            SELECT TRY_CAST(weather_date AS DATE)  AS weather_date,
                   TRY_CAST(temp_high_c AS DOUBLE) AS temp_high_c,
                   TRY_CAST(temp_low_c AS DOUBLE)  AS temp_low_c,
                   TRY_CAST(precip_mm AS DOUBLE)   AS precip_mm,
                   lower(nullif(condition, ''))    AS condition,
                   _batch_id, _row_number
            FROM bronze.weather""",
        rules=(
            ("unparseable weather_date", "weather_date IS NULL"),
            ("temperature missing or out of range [-50, 55]",
             "temp_high_c IS NULL OR temp_low_c IS NULL OR temp_high_c NOT BETWEEN -50 AND 55 "
             "OR temp_low_c NOT BETWEEN -50 AND 55"),
            ("temp_low_c above temp_high_c", "temp_low_c > temp_high_c"),
            ("precip_mm missing or negative", "precip_mm IS NULL OR precip_mm < 0"),
            ("unknown condition",
             "condition IS NULL OR condition NOT IN "
             "('clear', 'partly_cloudy', 'overcast', 'rain', 'snow')"),
        ),
        columns=("weather_date", "temp_high_c", "temp_low_c", "precip_mm", "condition"),
        project="weather_date, temp_high_c, temp_low_c, precip_mm, condition",
    ),
}

QUARANTINE_DDL = """
    CREATE TABLE IF NOT EXISTS silver.quarantine (
        dataset        VARCHAR NOT NULL,
        _batch_id      INTEGER NOT NULL,
        _row_number    BIGINT NOT NULL,
        reason         VARCHAR NOT NULL,
        record         JSON NOT NULL,
        quarantined_at TIMESTAMP NOT NULL
    )
"""


@dataclass(frozen=True)
class SilverResult:
    dataset: str
    batches: int
    read: int
    quarantined: int
    duplicates: int
    upserted: int


def _reason_expr(rules: tuple[tuple[str, str], ...]) -> str:
    whens = " ".join(f"WHEN coalesce({pred}, false) THEN '{reason}'" for reason, pred in rules)
    return f"CASE {whens} END"


def ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(QUARANTINE_DDL)
    for spec in SPECS.values():
        con.execute(spec.ddl)


def load_dataset(con: duckdb.DuckDBPyConnection, dataset: str) -> SilverResult:
    spec = SPECS[dataset]
    key = ", ".join(DATASETS[dataset].key)
    watermark = scalar(
        con, "SELECT last_batch_id FROM meta.watermarks WHERE dataset = ?", [dataset]
    ) or 0
    high = scalar(con, f"SELECT max(_batch_id) FROM bronze.{dataset}")
    if high is None or high <= watermark:
        return SilverResult(dataset, 0, 0, 0, 0, 0)

    con.execute("BEGIN")
    try:
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE _typed AS
            SELECT t.*, {_reason_expr(spec.rules)} AS _reject_reason
            FROM ({spec.typed}) t
            WHERE _batch_id > ?
            """,
            [watermark],
        )
        read = scalar(con, "SELECT count(*) FROM _typed")
        batches = scalar(con, "SELECT count(DISTINCT _batch_id) FROM _typed")
        con.execute(
            """
            INSERT INTO silver.quarantine
            SELECT ?, _batch_id, _row_number, _reject_reason,
                   to_json(t)::JSON, now()
            FROM _typed t WHERE _reject_reason IS NOT NULL
            """,
            [dataset],
        )
        quarantined = scalar(con, "SELECT count(*) FROM _typed WHERE _reject_reason IS NOT NULL")
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE _latest AS
            SELECT * FROM _typed
            WHERE _reject_reason IS NULL
            QUALIFY row_number() OVER (
                PARTITION BY {key} ORDER BY _batch_id DESC, _row_number DESC
            ) = 1
            """
        )
        upserted = scalar(con, "SELECT count(*) FROM _latest")
        cols = ", ".join(spec.columns)
        con.execute(
            f"""
            INSERT OR REPLACE INTO silver.{dataset} ({cols}, _batch_id, _updated_at)
            SELECT {spec.project}, _batch_id, now() FROM _latest
            """
        )
        con.execute(
            """
            INSERT OR REPLACE INTO meta.watermarks VALUES (?, ?, now())
            """,
            [dataset, high],
        )
        con.execute("DROP TABLE _typed")
        con.execute("DROP TABLE _latest")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return SilverResult(
        dataset, batches, read, quarantined, read - quarantined - upserted, upserted
    )


def load_all(con: duckdb.DuckDBPyConnection) -> list[SilverResult]:
    ensure_tables(con)
    return [load_dataset(con, name) for name in SPECS]
