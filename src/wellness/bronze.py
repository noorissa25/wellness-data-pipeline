"""Bronze: land raw files as-is (all strings), with lineage columns, exactly once.

Bronze never fixes data. It only refuses files that break the schema contract (missing
columns), so a malformed export fails loudly instead of silently producing nulls.
Each new file becomes one batch; a file whose content hash was already ingested is skipped,
which is what makes re-running the pipeline safe.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import duckdb

from wellness.config import DATASETS, Dataset
from wellness.warehouse import scalar

LINEAGE_COLUMNS = ("_batch_id", "_source_file", "_row_number", "_ingested_at")


class SchemaContractError(ValueError):
    """A landing file does not carry the columns its dataset requires."""


@dataclass(frozen=True)
class IngestedFile:
    dataset: str
    file_name: str
    batch_id: int
    rows: int


def _ensure_table(con: duckdb.DuckDBPyConnection, ds: Dataset) -> None:
    cols = ",\n".join(f"{c} VARCHAR" for c in ds.columns)
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS bronze.{ds.name} (
            {cols},
            _batch_id INTEGER NOT NULL,
            _source_file VARCHAR NOT NULL,
            _row_number BIGINT NOT NULL,
            _ingested_at TIMESTAMP NOT NULL
        )
        """
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_contract(path: Path, ds: Dataset) -> None:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        header = next(csv.reader(fh), [])
    missing = [c for c in ds.columns if c not in {h.strip() for h in header}]
    if missing:
        raise SchemaContractError(f"{path.name}: missing required column(s) {missing}")


def ingest_file(con: duckdb.DuckDBPyConnection, ds: Dataset, path: Path) -> IngestedFile | None:
    digest = _sha256(path)
    if scalar(con, "SELECT count(*) FROM meta.ingested_files WHERE sha256 = ?", [digest]):
        return None
    check_contract(path, ds)
    batch_id = scalar(con, "SELECT coalesce(max(batch_id), 0) + 1 FROM meta.ingested_files")
    select_cols = ", ".join(f'trim("{c}") AS {c}' for c in ds.columns)
    con.execute("BEGIN")
    try:
        con.execute(
            f"""
            INSERT INTO bronze.{ds.name}
            SELECT {select_cols}, ? , ?, row_number() OVER (), now()
            FROM read_csv(?, header = true, all_varchar = true)
            """,
            [batch_id, path.name, str(path)],
        )
        rows = scalar(
            con, f"SELECT count(*) FROM bronze.{ds.name} WHERE _batch_id = ?", [batch_id]
        )
        con.execute(
            "INSERT INTO meta.ingested_files VALUES (?, ?, ?, ?, ?, now())",
            [batch_id, ds.name, path.name, digest, rows],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return IngestedFile(ds.name, path.name, batch_id, rows)


def ingest_landing(con: duckdb.DuckDBPyConnection, landing_dir: Path) -> list[IngestedFile]:
    """Ingest every new landing file, oldest name first, one batch per file."""
    results = []
    for ds in DATASETS.values():
        _ensure_table(con, ds)
        for path in sorted((landing_dir / ds.name).glob("*.csv")):
            ingested = ingest_file(con, ds, path)
            if ingested:
                results.append(ingested)
    return results
