"""DuckDB connection and the metadata tables the pipeline keeps about itself."""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMAS = ("bronze", "silver", "gold", "meta")

META_DDL = (
    """
    CREATE TABLE IF NOT EXISTS meta.ingested_files (
        batch_id     INTEGER PRIMARY KEY,
        dataset      VARCHAR NOT NULL,
        file_name    VARCHAR NOT NULL,
        sha256       VARCHAR NOT NULL,
        row_count    INTEGER NOT NULL,
        ingested_at  TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta.watermarks (
        dataset        VARCHAR PRIMARY KEY,
        last_batch_id  INTEGER NOT NULL,
        updated_at     TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta.runs (
        run_id       INTEGER PRIMARY KEY,
        started_at   TIMESTAMP NOT NULL,
        finished_at  TIMESTAMP,
        status       VARCHAR NOT NULL,
        summary      VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta.dq_results (
        run_id       INTEGER NOT NULL,
        layer        VARCHAR NOT NULL,
        check_name   VARCHAR NOT NULL,
        severity     VARCHAR NOT NULL,
        failed_rows  BIGINT NOT NULL,
        passed       BOOLEAN NOT NULL,
        description  VARCHAR NOT NULL,
        checked_at   TIMESTAMP NOT NULL
    )
    """,
)


def connect(db_path: Path | str = ":memory:", read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        for schema in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for ddl in META_DDL:
            con.execute(ddl)
    return con


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None
