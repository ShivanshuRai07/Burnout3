"""Feature preparation for the 0-10 snapshot models.

The models learn directly from the measured columns. Earlier versions added hand-weighted composite
indexes (workload_index = 0.4*hours + 0.3*overtime + 0.2*meetings + 0.1*deadlines, a wellness score,
a support index and a meeting-load ratio). Their weights had no source, double-counted overtime inside
hours, gave meetings 20% although meetings are unrelated to burnout_score in the training data, and
divided a 20-200 column by 100. Tree models gain nothing from fixed mixes of columns they already see,
so the indexes were removed; the model learns how much each column matters.
"""
from __future__ import annotations

import pandas as pd

DEFAULT_NUMERIC_FEATURES = [
    "caffeine_intake", "deadlines_missed", "experience_years", "job_satisfaction",
    "manager_support", "meetings_per_day", "overtime_hours", "physical_activity_days",
    "screen_time_hours", "sleep_hours", "social_support_score", "stress_level",
    "work_hours_per_week", "work_life_balance",
]
DEFAULT_CATEGORICAL_FEATURES = ["company_size", "job_role", "work_mode"]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with numeric feature columns coerced to numbers; no derived indexes."""
    df = df.copy()
    for col in DEFAULT_NUMERIC_FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
