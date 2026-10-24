"""End to end: generate, run, re-run, add a batch, and break a check."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from wellness import cli, pipeline, quality, warehouse
from wellness.generate import GenerateConfig, write_landing

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def warehouse_con(tmp_path):
    con = warehouse.connect(tmp_path / "wh.duckdb")
    yield con
    con.close()


def test_full_run_then_rerun_is_a_no_op(tmp_path, warehouse_con):
    landing = tmp_path / "landing"
    write_landing(GenerateConfig(start=date(2026, 1, 1), days=120), landing)
    first = pipeline.run(warehouse_con, landing)
    assert len(first["bronze"]) == 6
    assert first["gold"]["daily_activity"] == 120

    before = warehouse_con.execute("SELECT * FROM gold.weekly_walking ORDER BY 1").fetchall()
    second = pipeline.run(warehouse_con, landing)
    assert second["bronze"] == []
    assert all(s["read"] == 0 for s in second["silver"])
    after = warehouse_con.execute("SELECT * FROM gold.weekly_walking ORDER BY 1").fetchall()
    assert after == before
    assert warehouse_con.execute("SELECT list(status ORDER BY run_id) FROM meta.runs"
                                 ).fetchone()[0] == ["succeeded", "succeeded"]


def test_new_batch_extends_gold(tmp_path, warehouse_con):
    landing = tmp_path / "landing"
    write_landing(GenerateConfig(start=date(2026, 1, 1), days=60), landing)
    pipeline.run(warehouse_con, landing)
    write_landing(GenerateConfig(start=date(2026, 3, 2), days=14, batches=1, seed=7), landing)
    summary = pipeline.run(warehouse_con, landing)
    assert {f["dataset"] for f in summary["bronze"]} == {"walk_sessions", "daily_steps", "weather"}
    assert summary["gold"]["daily_activity"] == 74


def test_failed_gold_check_keeps_previous_gold(tmp_path, warehouse_con, monkeypatch):
    landing = tmp_path / "landing"
    write_landing(GenerateConfig(start=date(2026, 1, 1), days=30), landing)
    pipeline.run(warehouse_con, landing)
    good = warehouse_con.execute("SELECT count(*) FROM gold.daily_activity").fetchone()[0]

    write_landing(GenerateConfig(start=date(2026, 1, 31), days=10, batches=1, seed=3), landing)
    broken = quality.GOLD_CHECKS + (quality.Check("gold", "broken", "error", "x", "SELECT 1"),)
    monkeypatch.setattr(quality, "GOLD_CHECKS", broken)
    with pytest.raises(quality.DataQualityError):
        pipeline.run(warehouse_con, landing)

    assert warehouse_con.execute("SELECT count(*) FROM gold.daily_activity").fetchone()[0] == good
    assert warehouse_con.execute("SELECT status FROM meta.runs ORDER BY run_id DESC LIMIT 1"
                                 ).fetchone()[0] == "failed"
    assert warehouse_con.execute("SELECT count(*) FROM meta.dq_results WHERE NOT passed "
                                 "AND check_name = 'broken'").fetchone()[0] == 1


def test_cli_and_dashboard(tmp_path, monkeypatch):
    assert cli.main(["--data-dir", str(tmp_path), "generate", "--days", "45"]) == 0
    assert cli.main(["--data-dir", str(tmp_path), "run"]) == 0

    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("WELLNESS_DATA_DIR", str(tmp_path))
    app = testing.AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    page = " ".join(str(e.proto) for e in app.get("html"))
    for section in ["summary", "walking", "longest", "weather", "pipeline"]:
        assert f'id=\\"{section}\\"' in page or f'id="{section}"' in page
