"""Table-level data-quality checks, recorded in ``meta.dq_results``.

Row-level problems are already handled in silver (bad rows are quarantined, not dropped).
These checks look at whole tables, where a single bad row is not visible: uniqueness,
completeness, cross-table consistency and reconciliation between layers. Each check is a
SQL query that returns the number of offending rows, so 0 means pass.

``error`` checks stop the run before gold is published (or before the run is marked
successful); ``warn`` checks are recorded and shown on the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from wellness.warehouse import scalar


class DataQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Check:
    layer: str
    name: str
    severity: str  # "error" | "warn"
    description: str
    sql: str  # returns a single count of failing rows


SILVER_CHECKS = (
    Check("silver", "walk_sessions_not_empty", "error",
          "silver.walk_sessions has at least one row",
          "SELECT CASE WHEN count(*) = 0 THEN 1 ELSE 0 END FROM silver.walk_sessions"),
    Check("silver", "walk_sessions_unique_id", "error",
          "session_id is unique",
          "SELECT count(*) - count(DISTINCT session_id) FROM silver.walk_sessions"),
    Check("silver", "daily_steps_unique_key", "error",
          "(activity_date, source) is unique",
          "SELECT count(*) FROM (SELECT activity_date, source FROM silver.daily_steps "
          "GROUP BY ALL HAVING count(*) > 1)"),
    Check("silver", "weather_unique_date", "error",
          "one weather row per date",
          "SELECT count(*) - count(DISTINCT weather_date) FROM silver.weather"),
    Check("silver", "quarantine_rate_below_5pct", "error",
          "under 5% of bronze rows per dataset are quarantined (a higher rate means a broken feed)",
          """
          SELECT count(*) FROM (
              SELECT b.dataset, b.n, coalesce(q.n, 0) AS bad
              FROM (SELECT 'walk_sessions' AS dataset, count(*) AS n FROM bronze.walk_sessions
                    UNION ALL SELECT 'daily_steps', count(*) FROM bronze.daily_steps
                    UNION ALL SELECT 'weather', count(*) FROM bronze.weather) b
              LEFT JOIN (SELECT dataset, count(*) AS n FROM silver.quarantine GROUP BY 1) q
                USING (dataset)
          ) WHERE n > 0 AND bad::DOUBLE / n >= 0.05
          """),
    Check("silver", "weather_covers_walk_dates", "warn",
          "every walk date has a weather row",
          "SELECT count(DISTINCT walk_date) FROM silver.walk_sessions w "
          "ANTI JOIN silver.weather x ON x.weather_date = w.walk_date"),
    Check("silver", "daily_steps_cover_walk_steps", "warn",
          "a day's step total is at least the steps recorded in that day's walks",
          """
          SELECT count(*) FROM (
              SELECT w.walk_date, w.source, sum(w.steps) AS walk_steps
              FROM silver.walk_sessions w WHERE w.steps IS NOT NULL GROUP BY ALL
          ) w JOIN silver.daily_steps d
            ON d.activity_date = w.walk_date AND d.source = w.source
          WHERE d.steps < w.walk_steps
          """),
    Check("silver", "no_sessions_overlap", "warn",
          "walk sessions from the same source do not overlap in time",
          """
          SELECT count(*) FROM silver.walk_sessions a JOIN silver.walk_sessions b
            ON a.source = b.source AND a.session_id < b.session_id
           AND a.start_ts < b.end_ts AND b.start_ts < a.end_ts
          """),
)

GOLD_CHECKS = (
    Check("gold", "daily_activity_no_gaps", "error",
          "gold.daily_activity has exactly one row per calendar day in its range",
          "SELECT (max(activity_date) - min(activity_date) + 1) - count(DISTINCT activity_date) "
          "+ (count(*) - count(DISTINCT activity_date)) FROM gold.daily_activity"),
    Check("gold", "weekly_km_reconciles_with_silver", "error",
          "total km in gold.weekly_walking equals total km in silver.walk_sessions",
          "SELECT CASE WHEN abs(coalesce((SELECT sum(total_km) FROM gold.weekly_walking), 0) - "
          "coalesce((SELECT sum(distance_km) FROM silver.walk_sessions), 0)) < 0.01 "
          "THEN 0 ELSE 1 END"),
    Check("gold", "weekly_walks_reconcile_with_silver", "error",
          "walk count in gold.weekly_walking equals silver.walk_sessions row count",
          "SELECT abs((SELECT coalesce(sum(walks), 0) FROM gold.weekly_walking) - "
          "(SELECT count(*) FROM silver.walk_sessions))"),
    Check("gold", "longest_walks_ranked", "error",
          "gold.longest_walks ranks are 1..n with no gaps",
          "SELECT count(*) FROM (SELECT rank_by_distance, row_number() OVER "
          "(ORDER BY rank_by_distance) AS rn FROM gold.longest_walks) "
          "WHERE rank_by_distance <> rn"),
    Check("gold", "weather_buckets_cover_days", "warn",
          "every day with weather lands in exactly one condition bucket",
          "SELECT abs((SELECT coalesce(sum(days), 0) FROM gold.walking_vs_weather "
          "WHERE dimension = 'condition') - (SELECT count(*) FROM gold.daily_activity "
          "WHERE condition IS NOT NULL))"),
)


def evaluate(con: duckdb.DuckDBPyConnection, checks: tuple[Check, ...]) -> list[dict]:
    """Run each check and return its result, without writing anything."""
    results = []
    for check in checks:
        failed = int(scalar(con, check.sql) or 0)
        results.append({"check": check, "failed_rows": failed, "passed": failed == 0})
    return results


def record(con: duckdb.DuckDBPyConnection, run_id: int, results: list[dict]) -> None:
    for r in results:
        c = r["check"]
        con.execute(
            "INSERT INTO meta.dq_results VALUES (?, ?, ?, ?, ?, ?, ?, now())",
            [run_id, c.layer, c.name, c.severity, r["failed_rows"], r["passed"], c.description],
        )


def raise_on_errors(results: list[dict]) -> None:
    errors = [r for r in results if r["check"].severity == "error" and not r["passed"]]
    if errors:
        names = ", ".join(f"{r['check'].name} ({r['failed_rows']})" for r in errors)
        raise DataQualityError(f"{errors[0]['check'].layer} checks failed: {names}")


def run_checks(
    con: duckdb.DuckDBPyConnection, run_id: int, checks: tuple[Check, ...]
) -> list[dict]:
    """Evaluate, record, then raise if any error-severity check failed."""
    results = evaluate(con, checks)
    record(con, run_id, results)
    raise_on_errors(results)
    return results
