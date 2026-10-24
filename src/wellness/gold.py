"""Gold: business-level tables the dashboard reads.

Gold is rebuilt in full from silver on each run. Silver is small (one row per walk or day),
so a rebuild takes milliseconds and guarantees that late corrections in silver (a revised
step count, a re-synced walk) flow into every aggregate without any merge logic.
The rebuild and the gold checks share one transaction: if a check fails, the previous
gold tables stay in place.
"""

from __future__ import annotations

import duckdb

GOLD_TABLES = {
    "daily_activity": """
        CREATE OR REPLACE TABLE gold.daily_activity AS
        WITH all_dates AS (
            SELECT activity_date AS d FROM silver.daily_steps
            UNION SELECT walk_date FROM silver.walk_sessions
        ),
        calendar AS (
            SELECT CAST(unnest(generate_series(min(d), max(d), INTERVAL 1 DAY)) AS DATE)
                   AS activity_date
            FROM all_dates
        ),
        walks AS (
            SELECT walk_date, count(*) AS walks, sum(distance_km) AS km,
                   sum(duration_min) AS minutes, max(distance_km) AS longest_km,
                   sum(steps) AS walk_steps
            FROM silver.walk_sessions GROUP BY 1
        ),
        steps AS (
            -- Several devices can report the same day; take the highest rather than summing.
            SELECT activity_date, max(steps) AS steps FROM silver.daily_steps GROUP BY 1
        )
        SELECT c.activity_date,
               CAST(date_trunc('week', c.activity_date) AS DATE) AS week_start,
               isodow(c.activity_date) >= 6                      AS is_weekend,
               coalesce(s.steps, w.walk_steps, 0)                AS steps,
               coalesce(w.walks, 0)                              AS walks,
               coalesce(w.km, 0)                                 AS walk_km,
               coalesce(w.minutes, 0)                            AS walk_minutes,
               coalesce(w.longest_km, 0)                         AS longest_walk_km,
               x.temp_high_c, x.temp_low_c, x.precip_mm, x.condition
        FROM calendar c
        LEFT JOIN steps s ON s.activity_date = c.activity_date
        LEFT JOIN walks w ON w.walk_date = c.activity_date
        LEFT JOIN silver.weather x ON x.weather_date = c.activity_date
        ORDER BY c.activity_date
    """,
    "weekly_walking": """
        CREATE OR REPLACE TABLE gold.weekly_walking AS
        SELECT week_start,
               count(*)                                   AS days_in_week,
               sum(walks)                                 AS walks,
               sum(walk_km)                               AS total_km,
               sum(walk_minutes) / 60                     AS total_hours,
               sum(steps)                                 AS total_steps,
               avg(steps)                                 AS avg_daily_steps,
               max(longest_walk_km)                       AS longest_walk_km,
               count(*) FILTER (WHERE walks > 0)          AS active_days,
               count(*) FILTER (WHERE steps >= 10000)     AS days_over_10k_steps
        FROM gold.daily_activity
        GROUP BY week_start
        ORDER BY week_start
    """,
    "longest_walks": """
        CREATE OR REPLACE TABLE gold.longest_walks AS
        SELECT row_number() OVER (ORDER BY w.distance_km DESC, w.start_ts) AS rank_by_distance,
               w.session_id, w.walk_date, w.start_ts, w.distance_km, w.duration_min,
               w.pace_min_per_km, w.steps, w.source,
               x.condition, x.temp_high_c
        FROM silver.walk_sessions w
        LEFT JOIN silver.weather x ON x.weather_date = w.walk_date
        QUALIFY rank_by_distance <= 25
        ORDER BY rank_by_distance
    """,
    "walking_vs_weather": """
        CREATE OR REPLACE TABLE gold.walking_vs_weather AS
        WITH d AS (
            SELECT *,
                   CASE WHEN temp_high_c < 0 THEN 1 WHEN temp_high_c < 10 THEN 2
                        WHEN temp_high_c < 20 THEN 3 WHEN temp_high_c < 30 THEN 4 ELSE 5
                   END AS temp_order
            FROM gold.daily_activity WHERE condition IS NOT NULL
        ),
        buckets AS (
            SELECT 'condition' AS dimension, condition AS bucket,
                   CASE condition WHEN 'clear' THEN 1 WHEN 'partly_cloudy' THEN 2
                        WHEN 'overcast' THEN 3 WHEN 'rain' THEN 4 ELSE 5 END AS bucket_order,
                   walks, walk_km, steps
            FROM d
            UNION ALL
            SELECT 'temperature',
                   ['below 0 °C', '0–10 °C', '10–20 °C', '20–30 °C', '30 °C and up'][temp_order],
                   temp_order, walks, walk_km, steps
            FROM d
        )
        SELECT dimension, bucket, bucket_order,
               count(*)                                         AS days,
               count(*) FILTER (WHERE walks > 0)                AS walk_days,
               avg(CASE WHEN walks > 0 THEN 1 ELSE 0 END)       AS share_days_walked,
               avg(walk_km)                                     AS avg_km_per_day,
               avg(walk_km) FILTER (WHERE walks > 0)            AS avg_km_on_walk_days,
               avg(steps)                                       AS avg_steps
        FROM buckets
        GROUP BY ALL
        ORDER BY dimension, bucket_order
    """,
}


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Rebuild every gold table, in dependency order. Caller owns the transaction."""
    counts = {}
    for name, sql in GOLD_TABLES.items():
        con.execute(sql)
        counts[name] = con.execute(f"SELECT count(*) FROM gold.{name}").fetchone()[0]
    return counts
