"""Adapters that turn phone/watch exports into the raw landing contract.

Each adapter only renames, converts units and filters. Validation, typing and dedup all
happen downstream in silver, so an imported file goes through exactly the same checks as
synthetic data.

Supported inputs:

* ``google-fit-daily``: Google Takeout ``Daily activity metrics.csv`` (``Date``, ``Step count``).
* ``apple-health-records``: Apple Health ``export.xml`` records flattened to CSV
  (``type, sourceName, unit, startDate, endDate, value``). Step records are summed per day.
* ``apple-health-workouts``: Apple Health workouts flattened to CSV
  (``workoutActivityType, duration, durationUnit, totalDistance, totalDistanceUnit,
  startDate, endDate``). Only walking and hiking workouts are kept.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wellness.config import DATASETS

FORMATS = ("google-fit-daily", "apple-health-records", "apple-health-workouts")
WALKING_WORKOUTS = {"HKWorkoutActivityTypeWalking", "HKWorkoutActivityTypeHiking"}
KM_PER_UNIT = {"km": 1.0, "mi": 1.609344, "m": 0.001}
MIN_PER_UNIT = {"min": 1.0, "s": 1 / 60, "hr": 60.0, "h": 60.0}


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _apple_ts(value: str) -> datetime:
    """Apple writes ``2026-03-01 08:12:44 -0500``. Keep the local wall-clock time."""
    return datetime.strptime(value.strip()[:19], "%Y-%m-%d %H:%M:%S")


def google_fit_daily(path: Path) -> dict[str, list[dict]]:
    rows = []
    for r in _read(path):
        steps = (r.get("Step count") or "").strip()
        if not steps:
            continue
        rows.append({"activity_date": r["Date"].strip(), "steps": steps, "source": "google_fit"})
    return {"daily_steps": rows}


def apple_health_records(path: Path) -> dict[str, list[dict]]:
    per_day: dict[str, float] = defaultdict(float)
    for r in _read(path):
        if r.get("type") != "HKQuantityTypeIdentifierStepCount":
            continue
        per_day[r["startDate"].strip()[:10]] += float(r["value"])
    rows = [
        {"activity_date": d, "steps": int(round(v)), "source": "apple_health"}
        for d, v in sorted(per_day.items())
    ]
    return {"daily_steps": rows}


def apple_health_workouts(path: Path) -> dict[str, list[dict]]:
    rows = []
    for r in _read(path):
        if r.get("workoutActivityType") not in WALKING_WORKOUTS:
            continue
        start, end = _apple_ts(r["startDate"]), _apple_ts(r["endDate"])
        duration = float(r["duration"]) * MIN_PER_UNIT[r.get("durationUnit", "min").strip()]
        km = float(r["totalDistance"]) * KM_PER_UNIT[r.get("totalDistanceUnit", "km").strip()]
        digest = hashlib.sha1(r["startDate"].strip().encode()).hexdigest()[:12]
        rows.append(
            {
                "session_id": f"ah-{digest}",
                "start_time": start.isoformat(timespec="minutes"),
                "end_time": end.isoformat(timespec="minutes"),
                "duration_min": round(duration, 1),
                "distance_km": round(km, 3),
                "steps": "",  # Apple workouts do not carry a step count
                "source": "apple_health",
            }
        )
    return {"walk_sessions": rows}


ADAPTERS = {
    "google-fit-daily": google_fit_daily,
    "apple-health-records": apple_health_records,
    "apple-health-workouts": apple_health_workouts,
}


def import_export(fmt: str, path: Path, landing_dir: Path) -> list[Path]:
    """Convert an export into landing files. Returns the files written."""
    if fmt not in ADAPTERS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
    written = []
    for dataset, rows in ADAPTERS[fmt](Path(path)).items():
        stem = Path(path).stem.lower().replace(" ", "_")
        out = landing_dir / dataset / f"{dataset}__{fmt.replace('-', '_')}__{stem}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(DATASETS[dataset].columns))
            writer.writeheader()
            writer.writerows(rows)
        written.append(out)
    return written
