"""Three reference points for flagging, and the individual-vs-systemic grid.

1. Absolute  - fixed CBI threshold and a working-time limit; catches whole divisions that are overloaded.
2. Division  - person vs colleagues in the same department and month (robust z-score); needs >= 5 people.
3. Personal  - person vs their own previous 3 scored months; available from the 4th month.

A division is "systemic" when significantly more of its people score high than the reference
population (binomial test) or its median working week exceeds the hours limit. Groups smaller than
MIN_GROUP are never reported.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from burnoutiq.assess import HIGH

MIN_GROUP = 5
HOURS_LIMIT = 48.0          # e.g. EU Working Time Directive average maximum; set to the local legal limit
DIVISION_Z = 2.0
PERSONAL_RISE = 10.0
FORECAST_RISE = 10.0
REFERENCE_NORM = {"source": "PUMA study 2004 (CBI manual)", "mean": 33.0, "pct_high": 19.8}


def _robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    return (x - med) / mad if mad > 0 else pd.Series(0.0, index=x.index)


def personal_baseline(history: pd.DataFrame, period: str, window: int = 3) -> pd.Series:
    """Mean of each employee's last `window` scored months before `period` (NaN if fewer)."""
    past = history[(history["period"] < period) & history["cbi_work_score"].notna()]
    last = past.sort_values("period").groupby("employee_id").tail(window)
    stats = last.groupby("employee_id")["cbi_work_score"].agg(["mean", "count"])
    return stats["mean"].where(stats["count"] >= window)


def workload_level(df: pd.DataFrame) -> pd.Series:
    """high / elevated / normal / no_data from measured hours and the perceived-workload item.

    high:     hours >= HOURS_LIMIT, or far above colleagues in the same department (robust z >= 2)
    elevated: hours more than 5 above the contract, or perceived workload 4-5 out of 5
    Kept separate from the burnout level: the interesting cases are where the two disagree.
    """
    nan = pd.Series(np.nan, index=df.index)
    hours = df.get("work_hours_per_week", nan)
    contract = df.get("contracted_hours_per_week", nan)
    perceived = df.get("perceived_workload_1_5", nan)
    high = (hours >= HOURS_LIMIT) | (df.get("division_hours_z", nan) >= DIVISION_Z)
    elevated = (hours > contract + 5) | (perceived >= 4)
    no_data = hours.isna() & perceived.isna()
    return pd.Series(np.select([no_data, high, elevated], ["no_data", "high", "elevated"], default="normal"),
                     index=df.index)


def employee_flags(current: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """current: one row per employee for the period being assessed (needs employee_id, department,
    cbi_work_score; optional work_hours_per_week, forecast)."""
    df = current.copy()
    period = df["period"].iloc[0]
    score = df["cbi_work_score"]
    hours = df.get("work_hours_per_week", pd.Series(np.nan, index=df.index))

    df["flag_absolute"] = score >= HIGH
    df["hours_over_limit"] = hours >= HOURS_LIMIT

    size = df.groupby("department")["cbi_work_score"].transform("count")
    df["division_score_z"] = df.groupby("department")["cbi_work_score"].transform(_robust_z).where(size >= MIN_GROUP)
    df["division_hours_z"] = df.groupby("department")["work_hours_per_week"].transform(_robust_z).where(
        size >= MIN_GROUP) if "work_hours_per_week" in df else np.nan
    df["flag_division"] = (df["division_score_z"] >= DIVISION_Z) | (df["division_hours_z"] >= DIVISION_Z)

    df["personal_baseline"] = df["employee_id"].map(personal_baseline(history, period))
    df["personal_change"] = score - df["personal_baseline"]
    df["flag_personal"] = df["personal_change"] >= PERSONAL_RISE

    if "forecast" in df:
        df["flag_forecast"] = (df["forecast"] >= HIGH) | ((df["forecast"] - score) >= FORECAST_RISE)
    else:
        df["flag_forecast"] = False

    df["workload_level"] = workload_level(df)

    reasons = {"flag_absolute": "score >= 50", "flag_division": "far above division",
               "flag_personal": "rising vs own baseline", "flag_forecast": "forecast high or rising"}
    flags = df[list(reasons)].fillna(False).astype(bool)
    df["flagged"] = flags.any(axis=1)
    df["flag_reasons"] = flags.apply(lambda r: "; ".join(reasons[c] for c in reasons if r[c]), axis=1)
    return df


def division_summary(flags: pd.DataFrame, norm: dict = REFERENCE_NORM) -> pd.DataFrame:
    rows = []
    for dept, g in flags.groupby("department"):
        scored = g["cbi_work_score"].dropna()
        n = len(scored)
        # everyone employed this month vs those who took the survey; non-takers are not in the scores
        took = {"n_employees": int(len(g)), "survey_rate": round(n / len(g), 3) if len(g) else None}
        if n < MIN_GROUP:
            rows.append({"department": dept, "n_scored": n, **took, "suppressed": True})
            continue
        n_high = int((scored >= HIGH).sum())
        p = binomtest(n_high, n, norm["pct_high"] / 100, alternative="greater").pvalue
        med_hours = float(g["work_hours_per_week"].median()) if "work_hours_per_week" in g else np.nan
        rows.append({
            "department": dept, "n_scored": n, **took, "suppressed": False,
            "mean_score": round(float(scored.mean()), 1), "pct_high": round(100 * n_high / n, 1),
            "reference_pct_high": norm["pct_high"], "p_more_high_than_reference": round(float(p), 4),
            "median_hours": round(med_hours, 1),
            "systemic": bool(p < 0.05 or med_hours >= HOURS_LIMIT),
            "n_flagged": int(g["flagged"].sum()),
        })
    return pd.DataFrame(rows)


def quadrant(flags: pd.DataFrame, divisions: pd.DataFrame) -> pd.Series:
    """individual / individual_and_systemic / systemic / healthy / no_score, per employee."""
    systemic = flags["department"].map(divisions.set_index("department").get("systemic")).fillna(False).astype(bool)
    person = flags["flagged"].astype(bool)
    no_score = flags["cbi_work_score"].isna()
    return pd.Series(np.select([person & systemic, person, no_score, systemic],
                               ["individual_and_systemic", "individual", "no_score", "systemic"], default="healthy"),
                     index=flags.index)
