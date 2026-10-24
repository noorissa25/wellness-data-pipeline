"""Seeded synthetic walking data.

Everything here is made up. The generator simulates a person who walks most days, walks
further on weekends, and walks less when it rains or the temperature is extreme. It then
slices the history into overlapping landing files, the way repeated exports from a phone
or watch overlap in practice, and (optionally) injects a small amount of mess so the
silver layer has real work to do:

* exact duplicate rows inside a file (double-synced sessions),
* invalid rows (negative distance, end before start, unparseable timestamps),
* revised daily step counts in the overlap window (a late sync from a second device).
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from wellness.config import DATASETS

SOURCE = "synthetic"


@dataclass(frozen=True)
class GenerateConfig:
    start: date = date(2025, 10, 1)
    days: int = 365
    seed: int = 42
    batches: int = 2
    overlap_days: int = 14
    noise: bool = True


def _weather_for(day: date, rng: random.Random) -> dict:
    # Temperate seasonal curve: coldest in late January, warmest in late July.
    doy = day.timetuple().tm_yday
    seasonal = 13 + 13 * math.sin(2 * math.pi * (doy - 110) / 365)
    high = round(seasonal + rng.gauss(0, 3.2), 1)
    low = round(high - rng.uniform(5, 11), 1)
    precip = 0.0
    if rng.random() < 0.32:
        precip = round(rng.expovariate(1 / 6.0), 1)
    if precip >= 0.5:
        condition = "snow" if high <= 1 else "rain"
    else:
        precip = 0.0
        condition = rng.choices(["clear", "partly_cloudy", "overcast"], weights=[4, 3, 2])[0]
    return {
        "weather_date": day.isoformat(),
        "temp_high_c": high,
        "temp_low_c": low,
        "precip_mm": precip,
        "condition": condition,
    }


def _walks_for(day: date, weather: dict, rng: random.Random) -> list[dict]:
    weekend = day.weekday() >= 5
    p_walk = 0.95 if weekend else 0.85
    distance_factor = 1.0
    if weather["condition"] == "rain":
        p_walk *= 0.55
        distance_factor = 0.7
    elif weather["condition"] == "snow":
        p_walk *= 0.4
        distance_factor = 0.6
    if weather["temp_high_c"] >= 31 or weather["temp_high_c"] <= -3:
        p_walk *= 0.6
        distance_factor *= 0.75

    if rng.random() >= p_walk:
        return []

    n_walks = 2 if rng.random() < 0.25 else 1
    walks = []
    for i in range(n_walks):
        if weekend and i == 0:
            km = rng.gauss(10, 3.5)
            if rng.random() < 0.12:  # the occasional very long walk
                km = rng.uniform(16, 28)
            start_hour = rng.uniform(8.5, 11)
        else:
            km = rng.gauss(5.5, 1.8)
            start_hour = rng.uniform(6.5, 8) if i == 0 else rng.uniform(17.5, 19.5)
        km = round(max(1.0, km * distance_factor), 2)
        pace = max(9.0, rng.gauss(11.6, 0.8))  # minutes per km
        duration = round(km * pace, 1)
        steps = int(km * 1000 / rng.uniform(0.7, 0.78))
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_hour)
        start = start.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=duration)
        walks.append(
            {
                "session_id": f"ws-{day:%Y%m%d}-{i + 1}",
                "start_time": start.isoformat(timespec="minutes"),
                "end_time": end.isoformat(timespec="minutes"),
                "duration_min": duration,
                "distance_km": km,
                "steps": steps,
                "source": SOURCE,
            }
        )
    return walks


def simulate(cfg: GenerateConfig) -> dict[str, list[dict]]:
    """Return the clean, full-history rows for every dataset."""
    rng = random.Random(cfg.seed)
    out: dict[str, list[dict]] = {name: [] for name in DATASETS}
    for offset in range(cfg.days):
        day = cfg.start + timedelta(days=offset)
        weather = _weather_for(day, rng)
        walks = _walks_for(day, weather, rng)
        background = max(500, int(rng.gauss(3800, 1300)))
        out["weather"].append(weather)
        out["walk_sessions"].extend(walks)
        out["daily_steps"].append(
            {
                "activity_date": day.isoformat(),
                "steps": background + sum(w["steps"] for w in walks),
                "source": SOURCE,
            }
        )
    return out


def _date_of(dataset: str, row: dict) -> date:
    field = {"walk_sessions": "start_time", "daily_steps": "activity_date"}.get(
        dataset, "weather_date"
    )
    return date.fromisoformat(str(row[field])[:10])


def _batch_windows(cfg: GenerateConfig) -> list[tuple[date, date]]:
    size = math.ceil(cfg.days / cfg.batches)
    windows = []
    for b in range(cfg.batches):
        lo = cfg.start + timedelta(days=max(0, b * size - (cfg.overlap_days if b else 0)))
        hi = cfg.start + timedelta(days=min(cfg.days, (b + 1) * size) - 1)
        windows.append((lo, hi))
    return windows


def _add_noise(dataset: str, rows: list[dict], rng: random.Random, revise: bool) -> list[dict]:
    rows = [dict(r) for r in rows]
    if dataset == "walk_sessions":
        for r in rng.sample(rows, k=max(1, len(rows) // 100)):
            rows.append(dict(r))  # exact duplicate
        bad = rng.sample(rows, k=len(rows) // 50)  # about 2% of rows
        for i, r in enumerate(bad):
            kind = i % 3
            if kind == 0:
                r["distance_km"] = -abs(float(r["distance_km"]))
            elif kind == 1:
                r["end_time"], r["start_time"] = r["start_time"], r["end_time"]
            else:
                r["start_time"] = "N/A"
    elif dataset == "daily_steps" and revise:
        # The first days of a later batch overlap the previous export with late-synced steps.
        for r in rows[:5]:
            r["steps"] = int(r["steps"]) + rng.randint(200, 1500)
    rng.shuffle(rows)
    return rows


def write_landing(cfg: GenerateConfig, landing_dir: Path) -> list[Path]:
    """Simulate the history and write it as overlapping landing files. Deterministic per seed."""
    full = simulate(cfg)
    noise_rng = random.Random(cfg.seed + 1)
    written = []
    for b, (lo, hi) in enumerate(_batch_windows(cfg)):
        for name, ds in DATASETS.items():
            rows = [r for r in full[name] if lo <= _date_of(name, r) <= hi]
            if cfg.noise:
                rows = _add_noise(name, rows, noise_rng, revise=b > 0)
            path = landing_dir / name / f"{name}__{SOURCE}__{lo:%Y%m%d}_{hi:%Y%m%d}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(ds.columns))
                writer.writeheader()
                writer.writerows(rows)
            written.append(path)
    return written
