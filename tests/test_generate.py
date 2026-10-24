from __future__ import annotations

from datetime import date

from wellness.generate import GenerateConfig, simulate, write_landing


def test_same_seed_same_files(tmp_path):
    cfg = GenerateConfig(start=date(2026, 1, 1), days=40)
    a = [p.read_bytes() for p in write_landing(cfg, tmp_path / "a")]
    b = [p.read_bytes() for p in write_landing(cfg, tmp_path / "b")]
    assert a == b


def test_different_seed_differs():
    a = simulate(GenerateConfig(days=30, seed=1))
    b = simulate(GenerateConfig(days=30, seed=2))
    assert a["walk_sessions"] != b["walk_sessions"]


def test_one_row_per_day_for_steps_and_weather():
    out = simulate(GenerateConfig(start=date(2026, 1, 1), days=60))
    assert len(out["daily_steps"]) == 60
    assert len({r["weather_date"] for r in out["weather"]}) == 60


def test_clean_walks_are_plausible():
    out = simulate(GenerateConfig(days=200))
    for w in out["walk_sessions"]:
        assert 1.0 <= w["distance_km"] <= 28
        assert 6 <= w["duration_min"] / w["distance_km"] <= 30
        assert w["end_time"] > w["start_time"]


def test_daily_steps_include_walk_steps():
    out = simulate(GenerateConfig(days=90))
    walk_steps: dict[str, int] = {}
    for w in out["walk_sessions"]:
        walk_steps[w["start_time"][:10]] = walk_steps.get(w["start_time"][:10], 0) + w["steps"]
    for d in out["daily_steps"]:
        assert d["steps"] >= walk_steps.get(d["activity_date"], 0)


def test_batches_overlap(tmp_path):
    cfg = GenerateConfig(start=date(2026, 1, 1), days=60, batches=2, overlap_days=10)
    files = sorted(p.name for p in write_landing(cfg, tmp_path) if "weather" in p.name)
    assert files == [
        "weather__synthetic__20260101_20260130.csv",
        "weather__synthetic__20260121_20260301.csv",
    ]


def test_noise_adds_duplicates_and_bad_rows(tmp_path):
    clean = GenerateConfig(days=365, batches=1, noise=False)
    noisy = GenerateConfig(days=365, batches=1, noise=True)
    n_clean = len(write_landing(clean, tmp_path / "c")[0].read_text().splitlines())
    noisy_text = write_landing(noisy, tmp_path / "n")[0].read_text()
    assert len(noisy_text.splitlines()) > n_clean
    assert "N/A" in noisy_text
