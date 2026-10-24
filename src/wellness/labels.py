"""Plain-English labels for quality checks and quarantine reasons, shared by the
Streamlit dashboard and the static site."""

CHECKS = {  # check_name -> (title, plain-English description)
    "walk_sessions_not_empty": ("Walk data present", "At least one walk was loaded."),
    "walk_sessions_unique_id": ("Walks are unique", "No walk appears twice."),
    "daily_steps_unique_key": ("Daily steps are unique", "One step total per day and device."),
    "weather_unique_date": ("Weather is unique", "One weather record per day."),
    "quarantine_rate_below_5pct": ("Feed looks healthy",
                                   "Under 5% of incoming rows were rejected."),
    "weather_covers_walk_dates": ("Weather covers every walk",
                                  "Every day with a walk has a weather record."),
    "daily_steps_cover_walk_steps": ("Step totals are consistent",
                                     "No day has fewer steps than its walks recorded."),
    "no_sessions_overlap": ("No overlapping walks",
                            "Walks from the same device never overlap in time."),
    "daily_activity_no_gaps": ("No missing days",
                               "The daily table has exactly one row per calendar day."),
    "weekly_km_reconciles_with_silver": ("Weekly distance adds up",
                                         "Weekly totals match the cleaned walk data exactly."),
    "weekly_walks_reconcile_with_silver": ("Weekly walk counts add up",
                                           "Weekly walk counts match the cleaned walk data."),
    "longest_walks_ranked": ("Rankings are complete",
                             "Longest-walk ranks run 1 to n with no gaps."),
    "weather_buckets_cover_days": ("Weather groups are complete",
                                   "Every day with weather falls into exactly one group."),
}
REASONS = {
    "missing session_id": "Missing session ID",
    "unparseable start_time": "Unreadable start time",
    "unparseable end_time": "Unreadable end time",
    "end_time not after start_time": "Ends before it starts",
    "duration_min missing or not positive": "Missing or zero duration",
    "distance_km missing or out of range [0.1, 80]": "Distance missing or out of range",
    "pace outside walking range [6, 30] min/km": "Pace outside walking range",
    "negative steps": "Negative step count",
}
