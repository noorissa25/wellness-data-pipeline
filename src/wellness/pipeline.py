"""The run: bronze -> silver -> silver checks -> gold + gold checks, logged in meta.runs."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import duckdb

from wellness import bronze, gold, quality, silver
from wellness.warehouse import scalar

log = logging.getLogger("wellness")


def run(con: duckdb.DuckDBPyConnection, landing_dir: Path) -> dict:
    run_id = scalar(con, "SELECT coalesce(max(run_id), 0) + 1 FROM meta.runs")
    con.execute("INSERT INTO meta.runs VALUES (?, now(), NULL, 'running', NULL)", [run_id])
    summary: dict = {"run_id": run_id}
    try:
        ingested = bronze.ingest_landing(con, landing_dir)
        summary["bronze"] = [asdict(f) for f in ingested]
        log.info("bronze: %d new file(s)", len(ingested))
        for f in ingested:
            log.info("  %-14s batch %-3d %5d rows  %s", f.dataset, f.batch_id, f.rows, f.file_name)

        loaded = silver.load_all(con)
        summary["silver"] = [asdict(r) for r in loaded]
        for r in loaded:
            log.info(
                "silver: %-14s read %5d  quarantined %3d  duplicates %3d  upserted %5d",
                r.dataset, r.read, r.quarantined, r.duplicates, r.upserted,
            )
        silver_results = quality.run_checks(con, run_id, quality.SILVER_CHECKS)
        _log_checks(silver_results)

        # Build and check gold in one transaction so a failed check never publishes.
        gold_results: list[dict] = []
        con.execute("BEGIN")
        try:
            summary["gold"] = gold.build(con)
            gold_results = quality.evaluate(con, quality.GOLD_CHECKS)
            quality.raise_on_errors(gold_results)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            quality.record(con, run_id, gold_results)
            raise
        quality.record(con, run_id, gold_results)
        _log_checks(gold_results)
        log.info("gold: %s", ", ".join(f"{k}={v}" for k, v in summary["gold"].items()))
    except Exception as exc:
        con.execute(
            "UPDATE meta.runs SET finished_at = now(), status = 'failed', summary = ? "
            "WHERE run_id = ?",
            [str(exc), run_id],
        )
        raise
    con.execute(
        "UPDATE meta.runs SET finished_at = now(), status = 'succeeded', summary = ? "
        "WHERE run_id = ?",
        [json.dumps(summary, default=str), run_id],
    )
    return summary


def _log_checks(results: list[dict]) -> None:
    for r in results:
        c = r["check"]
        status = "pass" if r["passed"] else ("FAIL" if c.severity == "error" else "warn")
        log.info("  dq %-6s %-5s %-36s failed_rows=%d", c.layer, status, c.name, r["failed_rows"])
