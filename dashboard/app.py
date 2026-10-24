"""Streamlit dashboard over the gold layer. Run with `make dashboard`."""

from __future__ import annotations

import os
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

DATA_DIR = Path(os.environ.get("WELLNESS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = DATA_DIR / "warehouse" / "wellness.duckdb"
BLUE = "#2a78d6"  # one hue: every chart here is a single series

st.set_page_config(page_title="Walking dashboard", page_icon="🚶", layout="wide")


@st.cache_data
def query(sql: str, _mtime: float, params: tuple = ()) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


if not DB_PATH.exists():
    st.error("No warehouse found. Run `make run` first, then reload this page.")
    st.stop()
mtime = DB_PATH.stat().st_mtime

st.title("Walking dashboard")
st.caption(
    "Built from the gold layer of the wellness pipeline. The default data is synthetic "
    "(seeded generator), not a real person's activity."
)

bounds = query("SELECT min(activity_date) lo, max(activity_date) hi FROM gold.daily_activity",
               mtime)
lo, hi = bounds.loc[0, "lo"].date(), bounds.loc[0, "hi"].date()
picked = st.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi)
start, end = (picked if isinstance(picked, tuple) and len(picked) == 2 else (lo, hi))

daily = query(
    "SELECT * FROM gold.daily_activity WHERE activity_date BETWEEN ? AND ? ORDER BY 1",
    mtime, (start, end),
)
weekly = query(
    "SELECT * FROM gold.weekly_walking WHERE week_start BETWEEN ? - INTERVAL 6 DAY AND ? "
    "ORDER BY 1", mtime, (start, end),
)

# ---- headline numbers -------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Distance walked", f"{daily.walk_km.sum():,.0f} km")
k2.metric("Walks", f"{int(daily.walks.sum()):,}")
k3.metric("Avg daily steps", f"{daily.steps.mean():,.0f}")
k4.metric("Longest walk", f"{daily.longest_walk_km.max():.1f} km")
k5.metric("Days with a walk", f"{(daily.walks > 0).mean():.0%}")

# ---- weekly totals ----------------------------------------------------------------------
st.subheader("Weekly distance")
weekly_chart = (
    alt.Chart(weekly)
    .mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X("week_start:T", title=None),
        y=alt.Y("total_km:Q", title="km per week"),
        tooltip=[
            alt.Tooltip("week_start:T", title="Week of"),
            alt.Tooltip("total_km:Q", title="km", format=".1f"),
            alt.Tooltip("walks:Q", title="Walks"),
            alt.Tooltip("total_hours:Q", title="Hours", format=".1f"),
            alt.Tooltip("longest_walk_km:Q", title="Longest (km)", format=".1f"),
        ],
    )
    .properties(height=260)
)
st.altair_chart(weekly_chart, use_container_width=True)

st.subheader("Daily steps, 7-day average")
steps = daily[["activity_date", "steps"]].copy()
steps["avg_7d"] = steps.steps.rolling(7, min_periods=1).mean()
hover = alt.selection_point(fields=["activity_date"], nearest=True, on="pointerover",
                            empty=False, clear="pointerout")
base = alt.Chart(steps).encode(x=alt.X("activity_date:T", title=None))
line = base.mark_line(color=BLUE, strokeWidth=2).encode(
    y=alt.Y("avg_7d:Q", title="steps (7-day average)")
)
points = base.mark_point(size=0, opacity=0).encode(
    tooltip=[alt.Tooltip("activity_date:T", title="Date"),
             alt.Tooltip("steps:Q", title="Steps", format=","),
             alt.Tooltip("avg_7d:Q", title="7-day avg", format=",.0f")]
).add_params(hover)
rule = base.mark_rule(color="gray").encode(
    opacity=alt.condition(hover, alt.value(0.5), alt.value(0))
)
st.altair_chart((line + points + rule).properties(height=240), use_container_width=True)

# ---- weather ----------------------------------------------------------------------------
st.subheader("Walking vs. weather")
in_range = daily.dropna(subset=["condition"]).copy()
in_range["walked"] = (in_range.walks > 0).astype(float)
bands = ["below 0 °C", "0–10 °C", "10–20 °C", "20–30 °C", "30 °C and up"]
in_range["temp_band"] = pd.cut(in_range.temp_high_c, [-100, 0, 10, 20, 30, 100],
                               right=False, labels=bands)
by_condition = (in_range.groupby("condition").agg(days=("walked", "size"),
                                                  share=("walked", "mean"),
                                                  km=("walk_km", "mean")).reset_index())
by_temp = (in_range.groupby("temp_band", observed=True)
           .agg(days=("walked", "size"), share=("walked", "mean"), km=("walk_km", "mean"))
           .reset_index())
cond_order = ["clear", "partly_cloudy", "overcast", "rain", "snow"]


def weather_bar(df: pd.DataFrame, field: str, order: list[str], title: str) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(f"{field}:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("km:Q", title="avg km walked per day"),
            tooltip=[alt.Tooltip(f"{field}:N", title=title),
                     alt.Tooltip("days:Q", title="Days"),
                     alt.Tooltip("share:Q", title="Days with a walk", format=".0%"),
                     alt.Tooltip("km:Q", title="Avg km per day", format=".1f")],
        )
        .properties(height=240, title=title)
    )


w1, w2 = st.columns(2)
w1.altair_chart(weather_bar(by_condition, "condition", cond_order, "By condition"),
                use_container_width=True)
w2.altair_chart(weather_bar(by_temp, "temp_band", bands, "By daily high temperature"),
                use_container_width=True)
st.caption("The full-history version of this breakdown is the `gold.walking_vs_weather` table.")

# ---- longest walks ----------------------------------------------------------------------
st.subheader("Longest walks")
longest = query(
    "SELECT rank_by_distance AS rank, walk_date, distance_km, duration_min, pace_min_per_km, "
    "condition, temp_high_c FROM gold.longest_walks WHERE walk_date BETWEEN ? AND ? "
    "ORDER BY rank_by_distance LIMIT 10",
    mtime, (start, end),
)
st.dataframe(
    longest, hide_index=True, use_container_width=True,
    column_config={
        "rank": st.column_config.NumberColumn("Rank (all time)"),
        "walk_date": st.column_config.DateColumn("Date"),
        "distance_km": st.column_config.NumberColumn("km", format="%.1f"),
        "duration_min": st.column_config.NumberColumn("Minutes", format="%.0f"),
        "pace_min_per_km": st.column_config.NumberColumn("Pace (min/km)", format="%.1f"),
        "condition": "Weather",
        "temp_high_c": st.column_config.NumberColumn("High °C", format="%.0f"),
    },
)

# ---- pipeline health --------------------------------------------------------------------
st.subheader("Pipeline health")
run = query("SELECT run_id, status, started_at, finished_at FROM meta.runs "
            "ORDER BY run_id DESC LIMIT 1", mtime)
dq = query(
    "SELECT layer, check_name, severity, passed, failed_rows, description FROM meta.dq_results "
    "WHERE run_id = (SELECT max(run_id) FROM meta.dq_results) ORDER BY layer DESC, check_name",
    mtime,
)
dq.insert(0, "status", [
    "✅ pass" if p else ("❌ fail" if s == "error" else "⚠️ warn")
    for p, s in zip(dq.passed, dq.severity)
])
quarantine = query("SELECT dataset, reason, count(*) AS rows FROM silver.quarantine "
                   "GROUP BY ALL ORDER BY rows DESC", mtime)
h1, h2 = st.columns([3, 2])
with h1:
    if not run.empty:
        r = run.iloc[0]
        finished = f"{r.finished_at:%Y-%m-%d %H:%M}"
        st.markdown(f"Last run **#{r.run_id}**: {r.status}, finished {finished}")
    st.dataframe(dq.drop(columns=["passed"]), hide_index=True, use_container_width=True)
with h2:
    st.markdown("**Quarantined rows** (kept in `silver.quarantine`, never silently dropped)")
    st.dataframe(quarantine, hide_index=True, use_container_width=True)

with st.expander("Daily data (table view)"):
    st.dataframe(daily, hide_index=True, use_container_width=True)
