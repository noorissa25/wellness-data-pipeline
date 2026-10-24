"""Streamlit dashboard over the gold layer. Run with `make preview`.

Distances are stored in kilometres throughout the warehouse and shown here in miles.
"""

from __future__ import annotations

import html
import os
from datetime import timedelta
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

DATA_DIR = Path(os.environ.get("WELLNESS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = DATA_DIR / "warehouse" / "wellness.duckdb"

MI_PER_KM = 0.621371
ACCENT = "#d63a2f"
ACCENT_SOFT = "#f6d3cf"
INK, MUTED, FAINT, LINE = "#141414", "#6f6f6f", "#9a9a9a", "#ececec"
GOOD, WARN = "#1f9d55", "#b7791f"
RANGES = {"Last 30 days": 30, "Last 90 days": 90, "Last 12 months": 365, "All time": None}

st.set_page_config(page_title="Stride · walking dashboard", page_icon="🚶", layout="wide")

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');

html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {{
  background: #f6f6f4; color: {INK};
  font-family: 'Inter', system-ui, sans-serif;
}}
[data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu {{ display: none; }}
.block-container {{
  max-width: 1120px; margin: 28px auto 48px; padding: 28px 44px 48px;
  background: #fff; border-radius: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 18px 48px rgba(20,20,20,.07);
}}
@media (max-width: 640px) {{
  .lede {{ font-size: 18px; }}
  .block-container {{ margin: 0; padding: 20px 16px 40px; border-radius: 0; box-shadow: none; }}
}}

/* brand + tabs */
.brand {{ display: inline-flex; align-items: center; gap: 8px; padding: 4px 12px 4px 6px;
  border: 1.5px solid {INK}; border-radius: 999px; font-weight: 800; font-size: 15px;
  letter-spacing: -.01em; font-style: italic; }}
.brand i {{ width: 18px; height: 18px; border-radius: 50%; background: {ACCENT};
  display: inline-block; }}
[data-baseweb="tab-list"] {{ gap: 28px; border-bottom: 1px solid {LINE}; }}
[data-baseweb="tab"] {{ padding: 10px 0; background: none; }}
[data-baseweb="tab"] p {{ font-size: 13px; font-weight: 500; color: {MUTED}; }}
[data-baseweb="tab"][aria-selected="true"] p {{ color: {INK}; font-weight: 600; }}
[data-baseweb="tab-highlight"] {{ background: {ACCENT}; height: 2px; }}
[data-baseweb="tab-border"] {{ display: none; }}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
  border-radius: 999px; font-size: 13px; min-height: 34px; background: #fff;
}}

/* type */
.page-title {{ font-size: 22px; font-weight: 700; letter-spacing: -.02em; margin: 18px 0 2px; }}
.page-sub {{ font-size: 13px; color: {MUTED}; margin-bottom: 26px; }}
.eyebrow {{ font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: {FAINT}; margin-bottom: 10px; }}
.lede {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 20px; line-height: 1.6;
  max-width: 66ch; color: {INK}; margin: 0 0 12px; }}
.note {{ font-size: 12px; color: {MUTED}; }}
.note b {{ color: {INK}; font-weight: 600; }}
.note a, .note .link {{ color: {ACCENT}; text-decoration: underline; text-underline-offset: 2px; }}

/* kpis */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  border-top: 1px solid {LINE}; margin: 34px 0 8px; }}
.kpi {{ padding: 18px 20px 4px 0; }}
.kpi + .kpi {{ padding-left: 20px; border-left: 1px solid {LINE}; }}
@media (max-width: 640px) {{
  .kpi + .kpi {{ border-left: none; padding-left: 0; border-top: 1px solid {LINE}; }}
}}
.kpi .num {{ font-size: 44px; font-weight: 800; letter-spacing: -.035em; line-height: 1.05; }}
.kpi .unit {{ font-size: 16px; font-weight: 700; margin-left: 3px; letter-spacing: 0; }}
.kpi .cap {{ font-size: 12px; color: {MUTED}; margin-top: 6px; line-height: 1.45; }}
.delta {{ font-size: 11.5px; font-weight: 600; }}
.delta.up {{ color: {GOOD}; }} .delta.down {{ color: {ACCENT}; }} .delta.flat {{ color: {FAINT}; }}

/* sections */
.section {{ margin-top: 36px; }}
.chart-title {{ font-size: 10.5px; font-weight: 600; letter-spacing: .08em;
  text-transform: uppercase; color: {FAINT}; margin: 30px 0 4px; }}

/* bar lists */
.bars {{ display: grid; gap: 2px; margin-top: 6px; }}
.bar-row {{ display: grid; grid-template-columns: minmax(110px, 190px) 1fr 84px;
  align-items: center; gap: 14px; padding: 9px 0; border-bottom: 1px solid #f3f3f1;
  font-size: 13px; }}
.bar-row .label {{ color: {INK}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.bar-row .label small {{ display: block; color: {FAINT}; font-size: 11px; }}
.bar-row .track {{ height: 6px; background: #f3f3f1; border-radius: 999px; overflow: hidden; }}
.bar-row .fill {{ height: 100%; background: {ACCENT}; border-radius: 999px; }}
.bar-row .val {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
.bars.compact .bar-row {{ grid-template-columns: 1fr 48px; }}
.bars.compact .bar-row .track {{ grid-column: 1 / -1; grid-row: 2; }}
@media (max-width: 640px) {{ .bar-row {{ grid-template-columns: 1fr 64px; }}
  .bar-row .track {{ grid-column: 1 / -1; grid-row: 2; }} }}

/* health */
.ring {{ width: 76px; height: 76px; border-radius: 50%; display: grid; place-items: center;
  flex: none; }}
.ring span {{ width: 62px; height: 62px; border-radius: 50%; background: #fff; display: grid;
  place-items: center; font-size: 22px; font-weight: 800; letter-spacing: -.02em; }}
.health {{ display: flex; gap: 22px; align-items: center; margin: 8px 0 26px; }}
.health h3 {{ font-size: 19px; font-weight: 700; letter-spacing: -.01em; margin: 0 0 4px; }}
.checks {{ border-top: 1px solid {LINE}; }}
.check {{ display: grid; grid-template-columns: 78px 1fr 70px; gap: 14px; padding: 12px 0;
  border-bottom: 1px solid #f3f3f1; font-size: 13px; align-items: start; }}
.check .name {{ font-weight: 600; }}
.check .desc {{ color: {MUTED}; font-size: 12px; margin-top: 2px; }}
.check .n {{ text-align: right; color: {MUTED}; font-variant-numeric: tabular-nums; }}
.pill {{ display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 9px;
  border-radius: 999px; }}
.pill.pass {{ background: #e7f5ec; color: {GOOD}; }}
.pill.warn {{ background: #fbf1df; color: {WARN}; }}
.pill.fail {{ background: #fbe5e3; color: {ACCENT}; }}
.layer {{ font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: {FAINT}; margin: 22px 0 6px; }}
[data-testid="stExpander"] {{ border: 1px solid {LINE}; border-radius: 12px; }}
</style>
"""
st.html(CSS)


# ---- data ---------------------------------------------------------------------------------
@st.cache_data
def query(sql: str, _mtime: float, params: tuple = ()) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


if not DB_PATH.exists():
    st.error("No warehouse found. Run `make run` first, then reload this page.")
    st.stop()
mtime = DB_PATH.stat().st_mtime

all_daily = query("SELECT * FROM gold.daily_activity ORDER BY activity_date", mtime)
all_daily["activity_date"] = pd.to_datetime(all_daily.activity_date)
all_daily["walk_mi"] = all_daily.walk_km * MI_PER_KM
all_daily["longest_walk_mi"] = all_daily.longest_walk_km * MI_PER_KM
all_daily["temp_high_f"] = all_daily.temp_high_c * 9 / 5 + 32
last_day = all_daily.activity_date.max()


# ---- helpers ------------------------------------------------------------------------------
def esc(value) -> str:
    return html.escape(str(value))


def fmt_day(ts) -> str:
    return f"{pd.Timestamp(ts):%-d %b %Y}"


def delta_html(now: float, before: float | None, label: str) -> str:
    if before is None or before == 0:
        return ""
    change = (now - before) / before
    cls = "flat" if abs(change) < 0.005 else ("up" if change > 0 else "down")
    arrow = {"up": "▲", "down": "▼", "flat": "●"}[cls]
    return f'<span class="delta {cls}">{arrow} {abs(change):.0%}</span> vs {esc(label)}'


def kpi(eyebrow: str, number: str, unit: str = "", caption: str = "") -> str:
    unit_html = f'<span class="unit">{esc(unit)}</span>' if unit else ""
    return (f'<div class="kpi"><div class="eyebrow">{esc(eyebrow)}</div>'
            f'<div class="num">{esc(number)}{unit_html}</div>'
            f'<div class="cap">{caption}</div></div>')


def bar_list(rows: list[tuple[str, str, float, str]], compact: bool = False) -> str:
    """rows: (label, sublabel, value for bar length, formatted value)."""
    top = max((r[2] for r in rows), default=0) or 1
    items = "".join(
        f'<div class="bar-row"><div class="label">{esc(label)}'
        f'{f"<small>{esc(sub)}</small>" if sub else ""}</div>'
        f'<div class="track"><div class="fill" style="width:{max(2, value / top * 100):.1f}%">'
        f'</div></div><div class="val">{esc(shown)}</div></div>'
        for label, sub, value, shown in rows
    )
    return f'<div class="bars{" compact" if compact else ""}">{items}</div>'


def ring(score: int, color: str) -> str:
    # CSS only: st.html sanitizes inline SVG away.
    return (f'<div class="ring" role="img" aria-label="Score {score} of 100" '
            f'style="background: conic-gradient({color} {score * 3.6:.0f}deg, {LINE} 0)">'
            f'<span>{score}</span></div>')


def styled(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeWidth=0)
        .configure_axis(labelColor=FAINT, labelFont="Inter", labelFontSize=11, titleColor=FAINT,
                        titleFont="Inter", titleFontSize=11, titleFontWeight=500,
                        domain=False, ticks=False, grid=False, labelPadding=8)
        .configure_axisY(grid=True, gridColor="#f1f1ef", tickCount=4)
    )


def area_chart(df: pd.DataFrame, x: str, y: str, y_title: str, tooltip: list,
               height: int = 230) -> alt.Chart:
    hover = alt.selection_point(fields=[x], nearest=True, on="pointerover", empty=False,
                                clear="pointerout")
    span = (df[x].max() - df[x].min()).days if len(df) else 0
    if span <= 45:
        ticks, fmt = {"interval": "week", "step": 1}, "%-d %b"
    elif span <= 120:
        ticks, fmt = {"interval": "week", "step": 2}, "%-d %b"
    else:
        ticks, fmt = {"interval": "month", "step": 1 if span <= 400 else 3}, "%b"
    base = alt.Chart(df).encode(x=alt.X(f"{x}:T", title=None, axis=alt.Axis(
        format=fmt, labelAngle=0, tickCount=ticks, labelOverlap=True)))
    area = base.mark_area(
        interpolate="monotone",
        line={"color": ACCENT, "strokeWidth": 2},
        color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                           stops=[alt.GradientStop(color="#ffffff", offset=0),
                                  alt.GradientStop(color=ACCENT_SOFT, offset=1)]),
    ).encode(y=alt.Y(f"{y}:Q", title=y_title))
    hit = base.mark_point(size=60, opacity=0).encode(y=f"{y}:Q", tooltip=tooltip).add_params(hover)
    dot = base.mark_point(filled=True, size=60, color=ACCENT, stroke="white", strokeWidth=2).encode(
        y=f"{y}:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    rule = base.mark_rule(color="#d9d9d6").encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    return styled((area + rule + hit + dot).properties(height=height))


# ---- header -------------------------------------------------------------------------------
left, right = st.columns([4, 1], vertical_alignment="center")
left.html('<span class="brand"><i></i>Stride</span>')
range_label = right.selectbox("Date range", list(RANGES), index=1, label_visibility="collapsed")

days = RANGES[range_label]
if days:
    start = last_day - timedelta(days=days - 1)
    daily = all_daily[all_daily.activity_date >= start]
    prior = all_daily[(all_daily.activity_date < start)
                      & (all_daily.activity_date >= start - timedelta(days=days))]
    prior = prior if len(prior) == days else None
    vs = f"prior {days} days"
else:
    daily, prior, vs = all_daily, None, ""

tab_summary, tab_walking, tab_longest, tab_weather, tab_pipeline = st.tabs(
    ["Summary", "Walking", "Longest walks", "Weather", "Pipeline health"]
)

dq = query(
    "SELECT layer, check_name, severity, passed, failed_rows, description FROM meta.dq_results "
    "WHERE run_id = (SELECT max(run_id) FROM meta.dq_results) ORDER BY layer DESC, check_name",
    mtime,
)
checks_passed, checks_total = int(dq.passed.sum()), len(dq)


def total(df, col):
    return None if df is None else float(df[col].sum())


miles, walks = daily.walk_mi.sum(), int(daily.walks.sum())
weeks = max(len(daily) / 7, 1)
share_walked = (daily.walks > 0).mean() if len(daily) else 0
best = daily.loc[daily.longest_walk_mi.idxmax()] if len(daily) else None

# ---- summary ------------------------------------------------------------------------------
with tab_summary:
    st.html('<div class="page-title">Summary</div>'
            '<div class="page-sub">The whole picture, in plain English</div>')

    wet = daily.condition.isin(["rain", "snow"])
    dry_share = (daily[~wet & daily.condition.notna()].walks > 0).mean()
    wet_share = (daily[wet].walks > 0).mean()
    sentences = [
        f"{'Over the ' + range_label.lower() if days else 'In total'}, this dataset logged "
        f"{miles:,.0f} miles across "
        f"{walks:,} walks, about {miles / weeks:,.0f} miles a week.",
        f"There was a walk on {share_walked:.0%} of days",
    ]
    if best is not None and best.longest_walk_mi > 0:
        sentences[-1] += (f", and the longest covered {best.longest_walk_mi:.1f} miles on "
                          f"{fmt_day(best.activity_date)}.")
    else:
        sentences[-1] += "."
    if wet.any() and pd.notna(dry_share) and pd.notna(wet_share):
        sentences.append(f"Weather matters: walks happened on {dry_share:.0%} of dry days but "
                         f"only {wet_share:.0%} of rainy or snowy ones.")
    sentences.append(
        "Every data-quality check passed on the last run, so these numbers are safe to read."
        if checks_passed == checks_total
        else f"{checks_total - checks_passed} data-quality check(s) need attention; "
             "see Pipeline health."
    )
    lede = " ".join(sentences)

    st.html(
        f'<div class="eyebrow">{esc(range_label)} · {fmt_day(daily.activity_date.min())} '
        f'to {fmt_day(daily.activity_date.max())}</div>'
        f'<p class="lede">{esc(lede)}</p>'
        f'<div class="note">Synthetic data from the seeded generator · '
        f'<b>{checks_passed} of {checks_total}</b> checks passed</div>'
        '<div class="kpis">'
        + kpi("Distance walked", f"{miles:,.0f}", "mi",
              delta_html(miles, total(prior, "walk_mi"), vs) or "total over the period")
        + kpi("Walks", f"{walks:,}", "",
              delta_html(walks, total(prior, "walks"), vs) or "sessions recorded")
        + kpi("Avg daily steps", f"{daily.steps.mean():,.0f}", "",
              delta_html(daily.steps.mean(),
                         None if prior is None else prior.steps.mean(), vs)
              or "highest device per day")
        + kpi("Days with a walk", f"{share_walked * 100:.0f}", "%",
              f"{int((daily.walks > 0).sum())} of {len(daily)} days")
        + "</div>"
    )

    weekly = (daily.set_index("activity_date").resample("W-MON", label="left", closed="left")
              .agg(walk_mi=("walk_mi", "sum"), walks=("walks", "sum")).reset_index())
    st.html('<div class="chart-title">Miles per week</div>')
    st.altair_chart(area_chart(
        weekly, "activity_date", "walk_mi", "",
        [alt.Tooltip("activity_date:T", title="Week of", format="%-d %b %Y"),
         alt.Tooltip("walk_mi:Q", title="Miles", format=".1f"),
         alt.Tooltip("walks:Q", title="Walks")]), use_container_width=True)

# ---- walking ------------------------------------------------------------------------------
with tab_walking:
    st.html('<div class="page-title">Walking</div>'
            '<div class="page-sub">Distance, time and steps, day by day</div>')
    hours = daily.walk_minutes.sum() / 60
    walk_days = daily[daily.walks > 0]
    st.html(
        '<div class="kpis" style="margin-top:0">'
        + kpi("Time on foot", f"{hours:,.0f}", "hrs", f"about {hours / weeks:.1f} hours a week")
        + kpi("Avg walk", f"{(miles / walks) if walks else 0:.1f}", "mi", "per session")
        + kpi("Avg pace",
              f"{(daily.walk_minutes.sum() / miles) if miles else 0:.1f}", "min/mi",
              "minutes per mile")
        + kpi("10k-step days", f"{int((daily.steps >= 10000).sum())}", "",
              f"{(daily.steps >= 10000).mean():.0%} of days")
        + "</div>"
    )
    steps = daily[["activity_date", "steps"]].copy()
    steps["avg_7d"] = steps.steps.rolling(7, min_periods=1).mean()
    st.html('<div class="chart-title">Daily steps · 7-day average</div>')
    st.altair_chart(area_chart(
        steps, "activity_date", "avg_7d", "",
        [alt.Tooltip("activity_date:T", title="Date", format="%-d %b %Y"),
         alt.Tooltip("steps:Q", title="Steps", format=","),
         alt.Tooltip("avg_7d:Q", title="7-day avg", format=",.0f")]), use_container_width=True)

    st.html('<div class="chart-title">Miles by day of week</div>')
    dow = (daily.assign(dow=daily.activity_date.dt.day_name())
           .groupby("dow").agg(mi=("walk_mi", "mean"), walked=("walks", lambda s: (s > 0).mean())))
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow = dow.reindex([d for d in order if d in dow.index])
    st.html(bar_list([(d, f"walked {r.walked:.0%} of the time", r.mi, f"{r.mi:.1f} mi")
                      for d, r in dow.iterrows()]))

    with st.expander("Daily data (table view)"):
        table = daily[["activity_date", "steps", "walks", "walk_mi", "walk_minutes",
                       "longest_walk_mi", "condition", "temp_high_f"]]
        st.dataframe(table, hide_index=True, use_container_width=True, column_config={
            "activity_date": st.column_config.DateColumn("Date"),
            "walk_mi": st.column_config.NumberColumn("Miles", format="%.1f"),
            "walk_minutes": st.column_config.NumberColumn("Minutes", format="%.0f"),
            "longest_walk_mi": st.column_config.NumberColumn("Longest (mi)", format="%.1f"),
            "temp_high_f": st.column_config.NumberColumn("High °F", format="%.0f"),
        })

# ---- longest walks ------------------------------------------------------------------------
with tab_longest:
    st.html('<div class="page-title">Longest walks</div>'
            '<div class="page-sub">The ten longest walks in the selected period</div>')
    longest = query(
        "SELECT walk_date, distance_km, duration_min, pace_min_per_km, condition, temp_high_c "
        "FROM silver.walk_sessions w LEFT JOIN silver.weather x ON x.weather_date = w.walk_date "
        "WHERE walk_date >= ? ORDER BY distance_km DESC, start_ts LIMIT 10",
        mtime, (daily.activity_date.min().date(),),
    )
    if longest.empty:
        st.html('<p class="note">No walks in this period.</p>')
    else:
        top = longest.iloc[0]
        st.html(
            '<div class="eyebrow">Longest in this period</div>'
            f'<p class="lede">{top.distance_km * MI_PER_KM:.1f} miles on '
            f'{fmt_day(top.walk_date)}, in {top.duration_min / 60:.1f} hours '
            f'({esc(str(top.condition).replace("_", " "))}, '
            f'high of {top.temp_high_c * 9 / 5 + 32:.0f} °F).</p>'
        )
        st.html(bar_list([
            (fmt_day(r.walk_date),
             f"{r.duration_min / 60:.1f} h · {r.pace_min_per_km * 1.609344:.1f} min/mi · "
             f"{str(r.condition).replace('_', ' ')}",
             r.distance_km, f"{r.distance_km * MI_PER_KM:.1f} mi")
            for r in longest.itertuples()
        ]))

# ---- weather ------------------------------------------------------------------------------
with tab_weather:
    st.html('<div class="page-title">Walking vs. weather</div>'
            '<div class="page-sub">How often, and how far, by sky and temperature</div>')
    w = daily.dropna(subset=["condition"]).copy()
    w["walked"] = (w.walks > 0).astype(float)
    bands = ["Below 32 °F", "32–50 °F", "50–68 °F", "68–86 °F", "86 °F and up"]
    w["band"] = pd.cut(w.temp_high_f, [-200, 32, 50, 68, 86, 200], right=False, labels=bands)

    def grouped(col, order):
        g = w.groupby(col, observed=True).agg(days=("walked", "size"), share=("walked", "mean"),
                                              mi=("walk_mi", "mean"))
        return g.reindex([o for o in order if o in g.index])

    cond = grouped("condition", ["clear", "partly_cloudy", "overcast", "rain", "snow"])
    temp = grouped("band", bands)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.html('<div class="chart-title">Share of days with a walk, by condition</div>'
                + bar_list([(k.replace("_", " ").capitalize(), f"{int(r.days)} days", r.share,
                             f"{r.share:.0%}") for k, r in cond.iterrows()]))
    with c2:
        st.html('<div class="chart-title">Average miles per day, by daily high</div>'
                + bar_list([(k, f"{int(r.days)} days", r.mi, f"{r.mi:.1f} mi")
                            for k, r in temp.iterrows()]))
    st.html('<p class="note" style="margin-top:18px">Full-history version: '
            '<span class="link">gold.walking_vs_weather</span>.</p>')

# ---- pipeline health ----------------------------------------------------------------------
with tab_pipeline:
    st.html('<div class="page-title">Pipeline health</div>'
            '<div class="page-sub">What the last run checked, and what it set aside</div>')
    run = query("SELECT run_id, status, finished_at FROM meta.runs ORDER BY run_id DESC LIMIT 1",
                mtime)
    files = query("SELECT count(*) AS files, coalesce(sum(row_count), 0) AS rows "
                  "FROM meta.ingested_files", mtime).iloc[0]
    quarantine = query("SELECT reason, count(*) AS n FROM silver.quarantine "
                       "GROUP BY 1 ORDER BY 2 DESC", mtime)
    score = round(100 * checks_passed / checks_total) if checks_total else 0
    errors = dq[(dq.severity == "error") & ~dq.passed]
    headline = ("Every check passed. The numbers are safe to read." if score == 100 else
                "Blocking checks failed. Gold was not updated." if len(errors) else
                "All blocking checks passed, with warnings to look at.")
    r = run.iloc[0] if not run.empty else None
    st.html(
        f'<div class="health">{ring(score, GOOD if not len(errors) else ACCENT)}<div>'
        f'<div class="eyebrow" style="margin:0 0 4px">Quality score</div>'
        f'<h3>{esc(headline)}</h3>'
        f'<div class="note">{checks_passed} of {checks_total} checks passed'
        + (f' · run #{r.run_id} {esc(r.status)} {r.finished_at:%-d %b %Y, %H:%M}' if r is not None
           else "")
        + f' · {int(files.files)} files, {int(files.rows):,} raw rows ingested</div></div></div>'
    )

    def check_row(c) -> str:
        status = "pass" if c.passed else ("fail" if c.severity == "error" else "warn")
        label = {"pass": "✓ Pass", "warn": "! Warn", "fail": "✕ Fail"}[status]
        return (f'<div class="check"><div><span class="pill {status}">{label}</span></div>'
                f'<div><div class="name">{esc(c.check_name.replace("_", " ").capitalize())}</div>'
                f'<div class="desc">{esc(c.description)}'
                f' · {"blocking" if c.severity == "error" else "warning"}</div></div>'
                f'<div class="n">{int(c.failed_rows)} rows</div></div>')

    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        for layer in ["silver", "gold"]:
            rows = dq[dq.layer == layer]
            st.html(f'<div class="layer">{layer} checks</div><div class="checks">'
                    + "".join(check_row(c) for c in rows.itertuples()) + "</div>")
    with c2:
        st.html('<div class="layer">Quarantined rows</div>'
                '<p class="note" style="margin:0 0 6px">Set aside in silver.quarantine with a '
                'reason, never silently dropped.</p>'
                + (bar_list([(q.reason, "", q.n, f"{q.n}")
                             for q in quarantine.itertuples()], compact=True)
                   if not quarantine.empty else '<p class="note">Nothing quarantined.</p>'))
