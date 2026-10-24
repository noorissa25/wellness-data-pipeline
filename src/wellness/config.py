"""Paths and the raw data contract shared by every layer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("WELLNESS_DATA_DIR", ROOT / "data"))
LANDING_DIR = DATA_DIR / "landing"
DB_PATH = DATA_DIR / "warehouse" / "wellness.duckdb"


@dataclass(frozen=True)
class Dataset:
    """A raw dataset: the columns every landing file must carry, and its business key."""

    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]


DATASETS: dict[str, Dataset] = {
    d.name: d
    for d in (
        Dataset(
            name="walk_sessions",
            columns=(
                "session_id",
                "start_time",
                "end_time",
                "duration_min",
                "distance_km",
                "steps",
                "source",
            ),
            key=("session_id",),
        ),
        Dataset(
            name="daily_steps",
            columns=("activity_date", "steps", "source"),
            key=("activity_date", "source"),
        ),
        Dataset(
            name="weather",
            columns=("weather_date", "temp_high_c", "temp_low_c", "precip_mm", "condition"),
            key=("weather_date",),
        ),
    )
}
