from __future__ import annotations

import csv
from pathlib import Path

import pytest

from wellness import bronze, silver, warehouse
from wellness.config import DATASETS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    c = warehouse.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    path = tmp_path / "landing"
    path.mkdir()
    return path


def write_landing_file(landing: Path, dataset: str, name: str, rows: list[dict]) -> Path:
    """Write rows (missing contract columns default to '') as a landing CSV."""
    path = landing / dataset / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(DATASETS[dataset].columns)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in cols})
    return path


def walk(session_id: str, start: str, minutes: float, km: float, steps="", source="test"):
    from datetime import datetime, timedelta

    t0 = datetime.fromisoformat(start)
    return {
        "session_id": session_id,
        "start_time": start,
        "end_time": (t0 + timedelta(minutes=minutes)).isoformat(timespec="minutes"),
        "duration_min": minutes,
        "distance_km": km,
        "steps": steps,
        "source": source,
    }


def load(con, landing: Path):
    """Run bronze + silver over the landing folder."""
    ingested = bronze.ingest_landing(con, landing)
    return ingested, {r.dataset: r for r in silver.load_all(con)}
