"""Input contract: three CSV files a company provides, and their validation.

employees.csv      one row per pseudonymous employee (from the HR system)
monthly.csv        one row per employee per month (CBI survey + optional work data)
interventions.csv  one row per support action logged by HR / managers

Only the CBI items are needed to run Assess and Verify (adoption level 1). Work data
(hours, meetings, ...) enables Predict and Simulate (level 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

CBI_ITEMS = [f"cbi_w{i}" for i in range(1, 8)]

EMPLOYEES_REQUIRED = ["employee_id", "department"]
EMPLOYEES_OPTIONAL = ["team_id", "role_type", "contracted_hours_per_week", "hire_date", "termination_date"]

MONTHLY_REQUIRED = ["employee_id", "period", *CBI_ITEMS]
MONTHLY_OPTIONAL = [
    "work_hours_per_week", "overtime_hours_per_week", "meeting_hours_per_week",
    "after_hours_messages_per_week", "pto_days_taken", "perceived_workload_1_5",
    "manager_support_1_5", "job_control_1_5", "work_life_balance_1_5",
    "job_satisfaction_1_5", "stress_level_0_10", "sleep_hours_avg",
]

INTERVENTIONS_REQUIRED = ["employee_id", "intervention_type", "referral_period", "start_date",
                          "planned_end_date", "completion_status"]
INTERVENTIONS_OPTIONAL = ["intervention_id", "trial_arm"]
COMPLETION_STATUSES = {"planned", "in_progress", "completed", "not_completed", "not_applicable"}

RANGES = {
    **{c: (0, 100) for c in CBI_ITEMS},
    "work_hours_per_week": (0, 100), "overtime_hours_per_week": (0, 80), "meeting_hours_per_week": (0, 60),
    "after_hours_messages_per_week": (0, 500), "pto_days_taken": (0, 31), "perceived_workload_1_5": (1, 5),
    "manager_support_1_5": (1, 5), "job_control_1_5": (1, 5), "work_life_balance_1_5": (1, 5),
    "job_satisfaction_1_5": (1, 5), "stress_level_0_10": (0, 10), "sleep_hours_avg": (0, 14),
}


class InputError(ValueError):
    """Raised when an input file cannot be used at all."""


@dataclass
class Inputs:
    employees: pd.DataFrame
    monthly: pd.DataFrame
    interventions: pd.DataFrame
    issues: list[str] = field(default_factory=list)


def _require(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise InputError(f"{name}: missing required columns {missing}")


def validate(employees: pd.DataFrame, monthly: pd.DataFrame, interventions: pd.DataFrame | None = None) -> Inputs:
    """Check structure, drop unusable rows and report every fix as an issue string."""
    issues: list[str] = []
    interventions = pd.DataFrame(columns=INTERVENTIONS_REQUIRED) if interventions is None else interventions
    _require(employees, EMPLOYEES_REQUIRED, "employees")
    _require(monthly, MONTHLY_REQUIRED, "monthly")
    _require(interventions, INTERVENTIONS_REQUIRED, "interventions")

    employees = employees.copy()
    employees["employee_id"] = employees["employee_id"].astype(str).str.strip()
    if employees["employee_id"].duplicated().any():
        n = int(employees["employee_id"].duplicated().sum())
        issues.append(f"employees: {n} duplicate employee_id rows dropped")
        employees = employees.drop_duplicates("employee_id")

    monthly = monthly.copy()
    monthly["employee_id"] = monthly["employee_id"].astype(str).str.strip()
    period = pd.to_datetime(monthly["period"].astype(str), format="%Y-%m", errors="coerce")
    bad_period = period.isna()
    if bad_period.any():
        issues.append(f"monthly: {int(bad_period.sum())} rows with period not in YYYY-MM format dropped")
    monthly = monthly[~bad_period].copy()
    monthly["period"] = period[~bad_period].dt.strftime("%Y-%m")

    unknown = ~monthly["employee_id"].isin(employees["employee_id"])
    if unknown.any():
        issues.append(f"monthly: {int(unknown.sum())} rows for employees not in employees.csv dropped")
        monthly = monthly[~unknown]
    dup = monthly.duplicated(["employee_id", "period"], keep="first")
    if dup.any():
        issues.append(f"monthly: {int(dup.sum())} duplicate employee-period rows dropped (kept first)")
        monthly = monthly[~dup]

    for col, (lo, hi) in RANGES.items():
        if col in monthly.columns:
            vals = pd.to_numeric(monthly[col], errors="coerce")
            bad = vals.notna() & ~vals.between(lo, hi)
            if bad.any():
                issues.append(f"monthly: {int(bad.sum())} {col} values outside {lo}-{hi} set to missing")
            monthly[col] = vals.where(~bad)

    interventions = interventions.copy()
    interventions["employee_id"] = interventions["employee_id"].astype(str).str.strip()
    status = interventions["completion_status"].astype(str).str.strip().str.lower()
    bad_status = ~status.isin(COMPLETION_STATUSES)
    if bad_status.any():
        issues.append(f"interventions: {int(bad_status.sum())} rows with unknown completion_status dropped "
                      f"(allowed: {sorted(COMPLETION_STATUSES)})")
    interventions = interventions[~bad_status].assign(completion_status=status[~bad_status])
    unknown_iv = ~interventions["employee_id"].isin(employees["employee_id"])
    if unknown_iv.any():
        issues.append(f"interventions: {int(unknown_iv.sum())} rows for unknown employees dropped")
        interventions = interventions[~unknown_iv]
    if "intervention_id" not in interventions.columns:
        interventions["intervention_id"] = [f"INT-{i + 1:05d}" for i in range(len(interventions))]
    interventions["referral_period"] = pd.to_datetime(
        interventions["referral_period"].astype(str), format="%Y-%m", errors="coerce").dt.strftime("%Y-%m")

    return Inputs(employees.reset_index(drop=True), monthly.reset_index(drop=True),
                  interventions.reset_index(drop=True), issues)


def read_csvs(employees: str | Path, monthly: str | Path, interventions: str | Path | None = None) -> Inputs:
    iv = pd.read_csv(interventions) if interventions else None
    return validate(pd.read_csv(employees), pd.read_csv(monthly), iv)


def write_templates(folder: str | Path) -> list[Path]:
    """Write empty CSV templates (headers only) a company can fill in."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = {
        "employees_template.csv": EMPLOYEES_REQUIRED + EMPLOYEES_OPTIONAL,
        "monthly_template.csv": MONTHLY_REQUIRED + MONTHLY_OPTIONAL,
        "interventions_template.csv": INTERVENTIONS_OPTIONAL[:1] + INTERVENTIONS_REQUIRED + INTERVENTIONS_OPTIONAL[1:],
    }
    paths = []
    for name, cols in files.items():
        p = folder / name
        pd.DataFrame(columns=cols).to_csv(p, index=False)
        paths.append(p)
    return paths
