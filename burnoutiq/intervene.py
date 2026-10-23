"""Stage 4 - Intervene: link each logged support action to before/after scores and track employee status.

Each intervention gets a baseline score (referral month), a follow-up score (first score in the
month the intervention ends or the month after) and an observed change. Employee status says where
each person is in the loop at a given month:

  monitoring -> flagged -> support_planned -> in_support -> follow_up_due / follow_up_overdue
             -> outcome_improved / outcome_no_change / outcome_worsened          (left = left the company)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from burnoutiq.verify import classify_change

FOLLOW_UP_GRACE = 1   # months after the planned end in which a follow-up score still counts


def _month(dates: pd.Series) -> pd.Series:
    return pd.to_datetime(dates, errors="coerce").dt.strftime("%Y-%m")


def _shift(period: pd.Series, months: int) -> pd.Series:
    p = pd.PeriodIndex(period.where(period.notna(), "1900-01"), freq="M") + months
    return pd.Series(p.astype(str), index=period.index).where(period.notna())


def link_scores(interventions: pd.DataFrame, scores: pd.DataFrame, rci: float) -> pd.DataFrame:
    """scores: employee_id, period, cbi_work_score (scored rows only)."""
    iv = interventions.copy()
    iv["start_period"] = _month(iv["start_date"])
    iv["end_period"] = _month(iv["planned_end_date"])
    # control arms and rows without an end date are followed up 3 months after referral
    iv["follow_up_period"] = iv["end_period"].fillna(_shift(iv["referral_period"], 3))

    s = scores.set_index(["employee_id", "period"])["cbi_work_score"]
    def lookup(periods: pd.Series) -> pd.Series:
        idx = pd.MultiIndex.from_arrays([iv["employee_id"], periods])
        return pd.Series(s.reindex(idx).to_numpy(), index=iv.index)

    iv["baseline_score"] = lookup(iv["referral_period"])
    on_time = lookup(iv["follow_up_period"])
    late = lookup(_shift(iv["follow_up_period"], FOLLOW_UP_GRACE))
    iv["follow_up_score"] = on_time.fillna(late)
    iv["follow_up_score_period"] = np.where(on_time.notna(), iv["follow_up_period"],
                                            np.where(late.notna(), _shift(iv["follow_up_period"], 1), None))
    iv["observed_change"] = (iv["follow_up_score"] - iv["baseline_score"]).round(2)
    return iv.join(classify_change(iv["observed_change"], rci))


def employee_status(employees: pd.DataFrame, flags: pd.DataFrame, linked: pd.DataFrame, period: str) -> pd.Series:
    """Status of every employee in `flags` at `period`, using only information available by then."""
    status = pd.Series(np.where(flags["flagged"], "flagged", "monitoring"), index=flags["employee_id"].to_numpy())

    term = employees.set_index("employee_id").get("termination_date")
    if term is not None:
        left = _month(term) <= period
        status[status.index.isin(left[left].index)] = "left"

    iv = linked[linked["referral_period"] <= period].sort_values("referral_period").groupby("employee_id").tail(1)
    for _, r in iv.iterrows():
        eid = r["employee_id"]
        if eid not in status.index or status[eid] == "left":
            continue
        if r["completion_status"] == "planned" or (pd.notna(r["start_period"]) and r["start_period"] > period):
            status[eid] = "support_planned"
        elif r["follow_up_period"] > period:
            status[eid] = "waitlist_control" if r["completion_status"] == "not_applicable" else "in_support"
        elif pd.notna(r["follow_up_score"]) and r["follow_up_score_period"] <= period:
            status[eid] = f"outcome_{r['outcome']}"
        elif _shift(pd.Series([r["follow_up_period"]]), FOLLOW_UP_GRACE).iloc[0] >= period:
            status[eid] = "follow_up_due"
        else:
            status[eid] = "follow_up_overdue"
    return status
