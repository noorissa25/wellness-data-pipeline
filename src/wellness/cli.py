"""Command line entry point: ``python -m wellness <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from wellness import config, importers, pipeline, site, warehouse
from wellness.generate import GenerateConfig, write_landing


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wellness", description=__doc__)
    p.add_argument("--data-dir", type=Path, default=config.DATA_DIR,
                   help="root for landing files and the warehouse (default: ./data)")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write seeded synthetic landing files")
    g.add_argument("--start", type=date.fromisoformat, default=GenerateConfig.start)
    g.add_argument("--days", type=int, default=GenerateConfig.days)
    g.add_argument("--seed", type=int, default=GenerateConfig.seed)
    g.add_argument("--batches", type=int, default=GenerateConfig.batches)
    g.add_argument("--overlap-days", type=int, default=GenerateConfig.overlap_days)
    g.add_argument("--no-noise", action="store_true", help="skip duplicate/invalid row injection")

    i = sub.add_parser("import", help="convert a phone/watch export into landing files")
    i.add_argument("format", choices=importers.FORMATS)
    i.add_argument("path", type=Path)

    sub.add_parser("run", help="ingest new landing files and rebuild silver and gold")
    sub.add_parser("status", help="show recent runs, watermarks and data-quality results")

    w = sub.add_parser("site", help="export the gold layer as a static web page")
    w.add_argument("--out", type=Path, default=Path("site"), help="output folder (default: ./site)")
    return p


def _status(db_path: Path) -> None:
    if not db_path.exists():
        print("no warehouse yet; run `make run` first")
        return
    con = warehouse.connect(db_path, read_only=True)
    for title, sql in (
        ("runs", "SELECT run_id, started_at, status FROM meta.runs ORDER BY run_id DESC LIMIT 5"),
        ("watermarks", "SELECT * FROM meta.watermarks ORDER BY dataset"),
        ("latest data-quality results",
         "SELECT layer, check_name, severity, passed, failed_rows FROM meta.dq_results "
         "WHERE run_id = (SELECT max(run_id) FROM meta.dq_results) "
         "ORDER BY layer DESC, check_name"),
        ("quarantine", "SELECT dataset, reason, count(*) AS rows FROM silver.quarantine "
                       "GROUP BY ALL ORDER BY dataset, rows DESC"),
    ):
        print(f"\n== {title}")
        con.sql(sql).show(max_width=120)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    landing = args.data_dir / "landing"
    db_path = args.data_dir / "warehouse" / "wellness.duckdb"

    if args.command == "generate":
        cfg = GenerateConfig(args.start, args.days, args.seed, args.batches,
                             args.overlap_days, not args.no_noise)
        for path in write_landing(cfg, landing):
            print(f"wrote {path.relative_to(args.data_dir)}")
    elif args.command == "import":
        for path in importers.import_export(args.format, args.path, landing):
            print(f"wrote {path.relative_to(args.data_dir)}")
    elif args.command == "run":
        con = warehouse.connect(db_path)
        try:
            pipeline.run(con, landing)
        except Exception as exc:  # surface a clean message; details are in meta.runs
            print(f"pipeline failed: {exc}", file=sys.stderr)
            return 1
        finally:
            con.close()
    elif args.command == "status":
        _status(db_path)
    elif args.command == "site":
        if not db_path.exists():
            print("no warehouse yet; run `make run` first", file=sys.stderr)
            return 1
        con = warehouse.connect(db_path, read_only=True)
        try:
            print(f"wrote {site.export_site(con, args.out)}")
        finally:
            con.close()
    return 0
