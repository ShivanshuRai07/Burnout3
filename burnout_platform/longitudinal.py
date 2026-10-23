"""Longitudinal forecasting, intervention tracking, and panel data management.

Provides reliable access to:
1. Historical assessment panel trends and burnout level distributions.
2. Next-period numerical forecasting (CBI 0-100 scale at t+1) with out-of-sample evaluation.
3. Intervention completion funnel, outcome status classification, and follow-up coverage.
4. Pseudonymous employee assessment timelines and linked intervention events.
5. Persistent action-management store for the Intervention Command Center.
"""
from __future__ import annotations

import functools
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import joblib

from burnoutiq import BurnoutLoop
from burnout_platform.loop_view import build_loop, forecast_payload, loop_payload

SUPPORT_TYPES = ["workload_review", "schedule_adjustment", "eap_counselling", "wellbeing_workshop"]
STATUS_UPDATES = {"started": "in_progress", "completed": "completed", "stopped": "not_completed"}
LOGGED_PREFIX = "LOG-"

RECORD_VERSION = 3   # records built from loop-verified scores; older cached files are rebuilt
OUTCOME_LABELS = {"improved": "improving", "no_change": "stable", "worsened": "worsening",
                  "no_follow_up": "insufficient_data"}

NON_CAUSAL_DISCLAIMER = (
    "Non-Causal Notice: Observed change only; not a causal effect estimate. "
    "A score reduction following an intervention does not prove the intervention caused the reduction "
    "without a randomized trial or counterfactual control."
)

SYNTHETIC_DATA_LABEL = (
    "Synthetic Demonstration Panel (burnoutiq_synthetic_v1). "
    "No open real-world dataset links individual workplace interventions to follow-up burnout scores."
)


def _locked(method):
    """Serialise tracker calls: the server is multi-threaded and data swaps must not interleave with reads."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def _next_month(period: str) -> str:
    return str(pd.Period(period, freq="M") + 1)


def _interventions_as_of(iv: pd.DataFrame, until: str) -> pd.DataFrame:
    """Interventions known by month `until`, with statuses as they were then (no later outcomes)."""
    iv = iv[iv["referral_period"].astype(str) <= until].copy()
    start = pd.to_datetime(iv["start_date"], errors="coerce").dt.strftime("%Y-%m")
    end = pd.to_datetime(iv["planned_end_date"], errors="coerce").dt.strftime("%Y-%m")
    real = iv["completion_status"].isin(["completed", "not_completed", "in_progress"])
    not_started = start.isna() | (start > until)
    iv.loc[real & not_started, "completion_status"] = "planned"
    iv.loc[real & ~not_started & (end > until), "completion_status"] = "in_progress"
    return iv


def _chronological(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by assessment date when the data has one (uploads may only have the month)."""
    return df.sort_values("assessment_date" if "assessment_date" in df.columns else "period")


def _date(value: Any) -> str:
    return "—" if value is None or (isinstance(value, float) and math.isnan(value)) or value == "" else str(value)


def classify_outcome_status(follow_up_observed: Any, observed_change: Any, threshold: float = 5.0) -> str:
    """Classify intervention outcome based on documented CBI threshold.
    
    - improving: observed_change <= -threshold
    - worsening: observed_change >= +threshold
    - stable: -threshold < observed_change < +threshold
    - insufficient_data: follow-up was not observed or missing
    """
    if not bool(follow_up_observed) or pd.isna(observed_change):
        return "insufficient_data"
    try:
        val = float(observed_change)
        if val <= -threshold:
            return "improving"
        elif val >= threshold:
            return "worsening"
        else:
            return "stable"
    except (ValueError, TypeError):
        return "insufficient_data"


class LongitudinalTracker:
    def __init__(self, data_dir: Optional[Path] = None, artifacts_dir: Optional[Path] = None) -> None:
        base = Path(__file__).resolve().parent.parent
        self.data_dir = data_dir or (base / "Datasets" / "burnoutiq_dataset" / "data")
        self.artifacts_dir = artifacts_dir or (base / "artifacts")
        self.records_path = self.artifacts_dir / "intervention_records.json"

        self.assessments_df: Optional[pd.DataFrame] = None
        self.interventions_df: Optional[pd.DataFrame] = None
        self.outcomes_df: Optional[pd.DataFrame] = None
        self.forecast_df: Optional[pd.DataFrame] = None
        self.forecast_model: Optional[Any] = None
        self.forecast_metrics: Dict[str, Any] = {}
        self.action_records: List[Dict[str, Any]] = []
        self.loop = None
        self.source: Dict[str, Any] = {"kind": "demo", "name": "Synthetic demonstration panel"}
        self._demo_state: Optional[Dict[str, Any]] = None
        self._checks: Dict[str, pd.DataFrame] = {}
        self._demo_full: Optional[Dict[str, pd.DataFrame]] = None
        self._lock = threading.RLock()

        self._load_datasets()
        try:
            self.loop = build_loop(self.data_dir)
        except Exception:
            self.loop = None
        self._init_or_load_action_records()

    # ── Uploaded data: run the loop on a company's own three CSV files ──────────
    _SWAPPED = ("assessments_df", "interventions_df", "outcomes_df", "forecast_df", "loop",
                "action_records", "records_path", "source", "_checks", "_demo_full")

    @_locked
    def load_upload(self, employees: pd.DataFrame, monthly: pd.DataFrame,
                    interventions: Optional[pd.DataFrame] = None, name: str = "Uploaded files") -> Dict[str, Any]:
        """Build and fit the loop on uploaded frames and make it the active data.

        Raises burnoutiq.schema.InputError for unusable files and ValueError when there is too little
        history to train the forecast. Uploaded data is kept in memory only, never written to disk.
        """
        loop = BurnoutLoop.from_frames(employees, monthly, interventions).fit()
        self._activate(loop, {"kind": "upload", "name": name}, checks={}, demo_full=None)
        return self.source

    def _activate(self, loop: BurnoutLoop, source: Dict[str, Any], checks: Dict[str, pd.DataFrame],
                  demo_full: Optional[Dict[str, pd.DataFrame]]) -> None:
        """Swap in a fitted loop with its source label in one step, so the two can never disagree."""
        if self._demo_state is None:
            self._demo_state = {k: getattr(self, k) for k in self._SWAPPED}
        new_source = {**source, "issues": list(loop.inputs.issues),
                      "employees": int(len(loop.inputs.employees)), "monthly": int(len(loop.records)),
                      "interventions": int(len(loop.inputs.interventions)),
                      "periods": [loop.periods[0], loop.periods[-1]]}
        self.loop, self.source, self._checks, self._demo_full = loop, new_source, checks, demo_full
        self.assessments_df = loop.records
        self.interventions_df = loop.inputs.interventions
        self.outcomes_df = None
        self.forecast_df = None
        self.records_path = None
        self.action_records = []
        try:
            self._init_or_load_action_records()
        except Exception:
            self.action_records = []

    @_locked
    def reset_to_demo(self) -> Dict[str, Any]:
        if self._demo_state is not None:
            for k, v in self._demo_state.items():
                setattr(self, k, v)
            self._demo_state = None
        return self.source

    # ── Month by month: start the demo one month early, then add months ─────────
    @_locked
    def start_live_demo(self, until: Optional[str] = None) -> Dict[str, Any]:
        """Run the demo panel only up to `until` (default: one month before its last month)."""
        full = {name: pd.read_csv(self.data_dir / f"{name}.csv") for name in ("employees", "assessments", "interventions")}
        periods = sorted(full["assessments"]["period"].astype(str).unique())
        until = until or periods[-2]
        if until not in periods[:-1]:
            raise ValueError(f"Choose a month between {periods[0]} and {periods[-2]} so there is a month left to add.")
        self.reset_to_demo()
        mon = full["assessments"][full["assessments"]["period"].astype(str) <= until]
        loop = BurnoutLoop.from_frames(full["employees"], mon, _interventions_as_of(full["interventions"], until)).fit()
        self._activate(loop, {"kind": "demo_live", "name": "Demo panel, month by month",
                              "next_period": _next_month(until) if _next_month(until) in periods else None},
                       checks={}, demo_full=full)
        return self.source

    @_locked
    def add_month(self, monthly: pd.DataFrame, interventions: Optional[pd.DataFrame] = None,
                  employees: Optional[pd.DataFrame] = None, replace_interventions: bool = False) -> Dict[str, Any]:
        """Append a new month of survey/work data and rerun the loop.

        Before the new month is added, the current model forecasts it for everyone, so the forecast
        can be compared with what actually happened (an honest out-of-sample check).
        """
        if self.loop is None:
            raise ValueError("No data loaded yet.")
        cur = self.loop.inputs
        last = self.loop.periods[-1]
        new_periods = sorted(pd.to_datetime(monthly["period"].astype(str), format="%Y-%m", errors="coerce")
                             .dt.strftime("%Y-%m").dropna().unique())
        if not new_periods:
            raise ValueError("The monthly file has no rows with a YYYY-MM period.")
        if new_periods[0] <= last:
            raise ValueError(f"The monthly file must only contain months after {last} (found {new_periods[0]}).")

        emp = cur.employees if employees is None else (
            pd.concat([cur.employees, employees]).drop_duplicates("employee_id", keep="last"))
        if interventions is None:
            iv = cur.interventions
        elif replace_interventions:
            iv = interventions
        else:
            iv = pd.concat([cur.interventions, interventions])
            if "intervention_id" in iv:
                iv = iv.drop_duplicates("intervention_id", keep="last")

        prior = self.loop.records[(self.loop.records["period"] == last) & self.loop.records["cbi_work_score"].notna()]
        predicted = self.loop.model.predict(prior).assign(employee_id=prior["employee_id"].to_numpy())

        loop = BurnoutLoop.from_frames(emp, pd.concat([cur.monthly, monthly], ignore_index=True), iv).fit()
        checks, demo_full = dict(self._checks), self._demo_full
        checks[_next_month(last)] = predicted
        nxt = _next_month(loop.periods[-1])
        more = demo_full is not None and nxt in set(demo_full["assessments"]["period"].astype(str))
        source = {"kind": self.source.get("kind", "upload"), "name": self.source.get("name", "Uploaded files"),
                  "months_added": self.source.get("months_added", 0) + len(new_periods), "next_period": nxt if more else None}
        self._activate(loop, source, checks=checks, demo_full=demo_full)
        return self.source

    @_locked
    def add_demo_month(self) -> Dict[str, Any]:
        if self._demo_full is None:
            raise ValueError("Start the month-by-month demo first.")
        nxt = _next_month(self.loop.periods[-1])
        full = self._demo_full
        mon = full["assessments"][full["assessments"]["period"].astype(str) == nxt]
        if mon.empty:
            raise ValueError("The demo has no more months to add.")
        iv = self.loop.inputs.interventions
        logged = iv[iv["intervention_id"].astype(str).str.startswith(LOGGED_PREFIX)]
        return self.add_month(mon, pd.concat([_interventions_as_of(full["interventions"], nxt), logged], ignore_index=True),
                              replace_interventions=True)

    # ── Intervene: a named person logs support; the loop verifies it when the next survey arrives ──
    @_locked
    def log_support(self, employee_id: str, intervention_type: str, owner: str, start_date: str,
                    planned_end_date: str, notes: str = "") -> Dict[str, Any]:
        """Add a support action decided after the latest month's survey (kept in memory only)."""
        if self.loop is None:
            raise ValueError("No data loaded yet.")
        cur = self.loop.inputs
        if employee_id not in set(cur.employees["employee_id"].astype(str)):
            raise ValueError(f"Unknown employee {employee_id}.")
        if intervention_type not in SUPPORT_TYPES:
            raise ValueError(f"Support type must be one of {', '.join(SUPPORT_TYPES)}.")
        if not str(owner or "").strip():
            raise ValueError("Name the person responsible for this support.")
        start, end = pd.to_datetime(start_date, errors="coerce"), pd.to_datetime(planned_end_date, errors="coerce")
        if pd.isna(start) or pd.isna(end) or end < start:
            raise ValueError("Give a start date and a planned end date on or after it.")
        # the "before" score is the person's latest answered survey; Verify compares the follow-up with it
        scored = self.loop.scores[self.loop.scores["employee_id"] == employee_id]
        if scored.empty:
            raise ValueError(f"{employee_id} has not answered a survey yet, so there is no score to compare against.")
        ids = cur.interventions["intervention_id"].astype(str)
        n = int(ids.str.startswith(LOGGED_PREFIX).sum()) + 1
        row = {"intervention_id": f"{LOGGED_PREFIX}{n:04d}", "employee_id": employee_id,
               "intervention_type": intervention_type, "referral_period": scored["period"].max(),
               "referral_reason": "manager_decision", "start_date": start.date().isoformat(),
               "planned_end_date": end.date().isoformat(), "completion_status": "planned", "trial_arm": "",
               "owner": str(owner).strip(), "notes": str(notes or "").strip()}
        self._rebuild(pd.concat([cur.interventions, pd.DataFrame([row])], ignore_index=True))
        return row

    @_locked
    def update_support(self, intervention_id: str, status: str) -> Dict[str, Any]:
        """started / completed / stopped for one support action."""
        if self.loop is None:
            raise ValueError("No data loaded yet.")
        if status not in STATUS_UPDATES:
            raise ValueError("Status must be started, completed or stopped.")
        iv = self.loop.inputs.interventions.copy()
        hit = iv["intervention_id"].astype(str) == str(intervention_id)
        if not hit.any():
            raise ValueError(f"Unknown support action {intervention_id}.")
        iv.loc[hit, "completion_status"] = STATUS_UPDATES[status]
        self._rebuild(iv)
        return {"intervention_id": intervention_id, "completion_status": STATUS_UPDATES[status]}

    def _rebuild(self, interventions: pd.DataFrame) -> None:
        """Refit the loop with changed interventions; same months, same source label."""
        cur = self.loop.inputs
        loop = BurnoutLoop.from_frames(cur.employees, cur.monthly, interventions).fit()
        keep = {k: v for k, v in self.source.items() if k in ("kind", "name", "months_added", "next_period")}
        self._activate(loop, keep, checks=self._checks, demo_full=self._demo_full)

    def predicted_vs_actual(self, period: str) -> Optional[Dict[str, Any]]:
        """Forecast made before `period` was added vs the scores that then arrived."""
        pred = self._checks.get(period)
        if pred is None or self.loop is None:
            return None
        actual = self.loop.records[(self.loop.records["period"] == period) & self.loop.records["cbi_work_score"].notna()]
        m = pred.merge(actual[["employee_id", "cbi_work_score", "department"]], on="employee_id")
        if m.empty:
            return None
        err = m["cbi_work_score"] - m["forecast"]
        inside = m["cbi_work_score"].between(m["forecast_low"], m["forecast_high"])
        by_dept = (m.assign(err=err).groupby("department")
                   .agg(n=("err", "size"), predicted=("forecast", "mean"), actual=("cbi_work_score", "mean"))
                   .round(1).reset_index())
        misses = m.assign(err=err.round(1)).reindex(err.abs().sort_values(ascending=False).index).head(5)
        return {"period": period, "n": int(len(m)), "mae": round(float(err.abs().mean()), 2),
                "mean_predicted": round(float(m["forecast"].mean()), 1),
                "mean_actual": round(float(m["cbi_work_score"].mean()), 1),
                "inside_range_pct": round(100 * float(inside.mean()), 1),
                "by_department": by_dept.to_dict("records"),
                "biggest_misses": misses[["employee_id", "department", "forecast", "cbi_work_score", "err"]].to_dict("records"),
                "note": "Forecast made from the previous month by the model as it was then, before this month's data existed."}

    @_locked
    def employee_rows(self, period: Optional[str] = None, department: str = "", team: str = "", level: str = "",
                      workload: str = "", status: str = "", flagged: bool = False, query: str = "",
                      sort: str = "score", page: int = 0, page_size: int = 25, quadrant: str = "") -> Dict[str, Any]:
        """Ranked, filterable employee list for one month, straight from the loop's output."""
        if self.loop is None:
            return {"available": False, "message": "No data loaded."}
        res = self.loop.run(period or None)
        df = res.employees
        facets = {"departments": sorted(df["department"].dropna().astype(str).unique().tolist()),
                  "teams": sorted(df.loc[df["department"] == department, "team_id"].dropna().astype(str).unique().tolist())
                  if department and "team_id" in df else []}
        for col, val in (("department", department), ("team_id", team), ("level", level),
                         ("workload_level", workload), ("status", status), ("quadrant", quadrant)):
            if val:
                df = df[df[col].astype(str).isin(str(val).split(","))]
        if flagged:
            df = df[df["flagged"].astype(bool)]
        if query:
            df = df[df["employee_id"].astype(str).str.contains(query.strip(), case=False, regex=False)]
        df = df.assign(forecast_change=df["forecast"] - df["cbi_work_score"])
        key = {"score": "cbi_work_score", "forecast": "forecast", "rise": "forecast_change",
               "personal_change": "personal_change", "hours": "work_hours_per_week"}.get(sort, "cbi_work_score")
        if sort == "urgent":   # people needing a decision first (flagged, no support yet), then by score
            df = (df.assign(_wait=df["status"].eq("flagged"))
                    .sort_values(["_wait", "cbi_work_score"], ascending=[False, False], na_position="last").drop(columns="_wait"))
        else:
            df = df.sort_values(key, ascending=False, na_position="last")
        counts = {c: df[c].value_counts().to_dict() for c in ("level", "workload_level", "status")}
        total = int(len(df))
        page_size = max(1, min(int(page_size), 200))
        pages = max(1, -(-total // page_size))
        page = max(0, min(int(page), pages - 1))
        rows = df.iloc[page * page_size:(page + 1) * page_size].replace({np.nan: None}).to_dict("records")
        # last 6 months of each listed person's score, up to the viewed month, for the trend sparkline
        months = [p for p in self.loop.periods if p <= res.period][-6:]
        hist = self.loop.records[self.loop.records["employee_id"].isin([r["employee_id"] for r in rows])
                                 & self.loop.records["period"].isin(months)]
        table = hist.pivot_table(index="employee_id", columns="period", values="cbi_work_score")
        for r in rows:
            s = table.loc[r["employee_id"]] if r["employee_id"] in table.index else None
            r["trend"] = [None if s is None or p not in s.index or pd.isna(s[p]) else round(float(s[p]), 1) for p in months]
        return {"available": True, "period": res.period, "total": total, "page": page, "pages": pages,
                "rows": rows, "counts": counts, "facets": facets}

    @_locked
    def try_survey(self, answers: Dict[str, Any], hours: float = 40.0, department: str = "") -> Dict[str, Any]:
        """Score one filled-in survey and show how the forecast for next month moves with working hours.

        The score comes from the answers only (that is the measure). Hours change the forecast, because the
        model learned that people working longer weeks tend to score higher next month (an association).
        Nothing is stored.
        """
        if self.loop is None:
            raise ValueError("No data loaded yet.")
        from burnoutiq.assess import CBI_ITEMS, level as cbi_level, score_cbi

        row = {c: pd.to_numeric(answers.get(c), errors="coerce") for c in CBI_ITEMS}
        if sum(pd.notna(v) for v in row.values()) < 4:
            raise ValueError("Answer at least 4 of the 7 questions.")
        if any(pd.notna(v) and v not in (0, 25, 50, 75, 100) for v in row.values()):
            raise ValueError("Answers must be 0, 25, 50, 75 or 100.")
        score = float(score_cbi(pd.DataFrame([row])).iloc[0])
        model = self.loop.model
        dept = department or str(self.loop.inputs.employees["department"].mode().iat[0])
        grid = list(range(30, 71))
        frame = pd.DataFrame([{"cbi_work_score": score, "work_hours_per_week": h,
                               "overtime_hours_per_week": max(0.0, h - 40.0), "department": dept} for h in grid])
        # other categories (role, work mode) at their most common value, as text like the training data
        for col in model.categorical:
            if col != "department":
                frame[col] = str(self.loop.records[col].dropna().astype(str).mode().iat[0]) if col in self.loop.records else ""
        pred = model.predict_mean(frame)
        at = float(model.predict_mean(frame.iloc[[min(range(len(grid)), key=lambda i: abs(grid[i] - hours))]])[0])
        return {"ok": True, "score": round(score, 1), "level": str(cbi_level(pd.Series([score])).iat[0]),
                "hours": hours, "department": dept, "forecast": round(at, 1),
                "interval_95": round(model.interval_95, 1),
                "by_hours": [{"hours": h, "forecast": round(float(p), 1)} for h, p in zip(grid, pred)],
                "note": "Score = average of the 7 answers (item 7 reversed). Hours move the forecast, not the score."}

    @_locked
    def data_summary(self) -> Dict[str, Any]:
        """What is loaded: surveys per month, field completeness, input counts and issues (for the Data page).

        Work-system fields are measured on every record; survey fields only on people who answered that month.
        """
        if self.loop is None:
            return {"available": False, "message": "No data loaded."}
        from burnoutiq.schema import MONTHLY_OPTIONAL

        rec, inp = self.loop.records, self.loop.inputs
        answered = rec["cbi_work_score"].notna()
        months = (rec.assign(answered=answered).groupby("period")
                  .agg(records=("employee_id", "size"), answered=("answered", "sum"), mean_score=("cbi_work_score", "mean"))
                  .reset_index())
        months["response_rate"] = (months["answered"] / months["records"]).round(3)
        months["mean_score"] = months["mean_score"].round(1)
        system = ["work_hours_per_week", "overtime_hours_per_week", "meeting_hours_per_week",
                  "after_hours_messages_per_week", "pto_days_taken"]
        fields = []
        for col in MONTHLY_OPTIONAL:
            if col not in rec:
                fields.append({"field": col, "group": "system" if col in system else "survey", "complete": None})
                continue
            base = rec if col in system else rec[answered]
            fields.append({"field": col, "group": "system" if col in system else "survey",
                           "complete": round(float(base[col].notna().mean()), 3) if len(base) else None})
        iv = inp.interventions
        logged = int(iv["intervention_id"].astype(str).str.startswith(LOGGED_PREFIX).sum()) if "intervention_id" in iv else 0
        return {"available": True, "source": self.source, "months": months.replace({np.nan: None}).to_dict("records"),
                "fields": fields, "employees": int(len(inp.employees)),
                "departments": int(inp.employees["department"].nunique()),
                "teams": int(inp.employees["team_id"].nunique()) if "team_id" in inp.employees else None,
                "records": int(len(rec)), "answered": int(answered.sum()),
                "interventions": int(len(iv)), "logged_here": logged, "issues": list(inp.issues),
                "level": 2 if sum(1 for f in fields if (f["complete"] or 0) > 0.5) else 1}

    @_locked
    def seat_rows(self, period: Optional[str] = None) -> Dict[str, Any]:
        """Everyone with a record this month as [employee_id, department, team, state], for the stadium chart.

        state: d = flagged, no support decided yet · s = support planned / under way / follow-up due ·
               f = flagged, other (e.g. after a result) · w = watch (one high month) · o = ok · n = no score
        """
        if self.loop is None:
            return {"available": False, "message": "No data loaded."}
        res = self.loop.run(period or None)
        df = res.employees
        support = df["status"].isin(["support_planned", "in_support", "follow_up_due", "follow_up_overdue"])
        state = np.select([df["status"].eq("flagged"), support & df["flagged"], df["flagged"],
                           df["trajectory_level"].eq("watch"), df["cbi_work_score"].isna()],
                          ["d", "s", "f", "w", "n"], default="o")
        rows = list(zip(df["employee_id"].astype(str), df["department"].astype(str),
                        df["team_id"].astype(str), state.tolist()))
        return {"available": True, "period": res.period, "rows": rows}

    @_locked
    def team_rows(self, period: Optional[str] = None, department: str = "", sort: str = "score") -> Dict[str, Any]:
        """Teams ranked for one month: score, share high, flagged, forecast rise, hours, change since last month.

        Teams with fewer than 5 scored people are listed without scores (same privacy rule as departments).
        "Running hot" = more high scores than the company rate would give by chance (one-sided binomial, p < 0.05).
        """
        if self.loop is None:
            return {"available": False, "message": "No data loaded."}
        from scipy.stats import binomtest

        res = self.loop.run(period or None)
        df = res.employees
        prev_p = [p for p in self.loop.periods if p < res.period]
        prev = self.loop.records[self.loop.records["period"] == prev_p[-1]] if prev_p else None
        prev_mean = (prev.groupby("team_id")["cbi_work_score"].mean() if prev is not None else pd.Series(dtype=float))
        scored_all = df["cbi_work_score"].notna()
        company_rate = float((df.loc[scored_all, "cbi_work_score"] >= 50).mean()) if scored_all.any() else 0.0
        rows = []
        for (dept, team), g in df.groupby(["department", "team_id"]):
            if department and dept not in department.split(","):
                continue
            s = g["cbi_work_score"].dropna()
            row = {"department": dept, "team_id": team, "n": int(len(g)), "n_scored": int(len(s)),
                   "survey_rate": round(len(s) / len(g), 3) if len(g) else None,
                   "n_flagged": int(g["flagged"].astype(bool).sum()), "suppressed": len(s) < 5,
                   # urgency: flagged with no support yet, very high now, gone quiet after a high score
                   "n_needs_decision": int(g["status"].eq("flagged").sum()),
                   "n_very_high": int(g["level"].eq("very_high").sum()),
                   "n_gone_quiet": int((g["trajectory_level"].eq("flagged") & g["cbi_work_score"].isna()).sum())}
            if not row["suppressed"]:
                high = int((s >= 50).sum())
                mean = float(s.mean())
                fc = g.loc[g["cbi_work_score"].notna(), "forecast"].dropna()
                pm = prev_mean.get(team)
                row.update({
                    "mean_score": round(mean, 1), "n_high": high, "pct_high": round(100 * high / len(s), 1),
                    "mean_forecast": round(float(fc.mean()), 1) if len(fc) else None,
                    "rise": round(float(fc.mean()) - mean, 1) if len(fc) else None,
                    "change": round(mean - float(pm), 1) if pm is not None and not pd.isna(pm) else None,
                    "mean_hours": round(float(g["work_hours_per_week"].mean()), 1) if g["work_hours_per_week"].notna().any() else None,
                    "hot": bool(high and binomtest(high, len(s), company_rate, alternative="greater").pvalue < 0.05),
                })
            rows.append(row)
        key = {"urgent": "n_needs_decision", "score": "mean_score", "high": "pct_high", "flagged": "n_flagged", "rise": "rise",
               "change": "change", "hours": "mean_hours"}.get(sort, "mean_score")
        rows.sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0)))
        return {"available": True, "period": res.period, "company_pct_high": round(100 * company_rate, 1),
                "previous_period": prev_p[-1] if prev_p else None, "rows": rows,
                "n_hot": sum(r.get("hot", False) for r in rows), "n_hidden": sum(r["suppressed"] for r in rows)}

    def _load_datasets(self) -> None:
        """Load datasets if available on disk."""
        assessments_p = self.data_dir / "assessments.csv"
        if assessments_p.exists():
            try:
                self.assessments_df = pd.read_csv(assessments_p)
            except Exception:
                self.assessments_df = None

        interventions_p = self.data_dir / "interventions.csv"
        if interventions_p.exists():
            try:
                self.interventions_df = pd.read_csv(interventions_p)
            except Exception:
                self.interventions_df = None

        outcomes_p = self.data_dir / "intervention_outcomes_view.csv"
        if outcomes_p.exists():
            try:
                self.outcomes_df = pd.read_csv(outcomes_p)
            except Exception:
                self.outcomes_df = None

        forecast_p = self.data_dir / "forecast_t_to_t1.csv"
        if forecast_p.exists():
            try:
                self.forecast_df = pd.read_csv(forecast_p)
            except Exception:
                self.forecast_df = None

        model_p = self.artifacts_dir / "forecast_model.joblib"
        if model_p.exists():
            try:
                self.forecast_model = joblib.load(model_p)
            except Exception:
                self.forecast_model = None

        metrics_p = self.artifacts_dir / "forecast_metrics.json"
        if metrics_p.exists():
            try:
                self.forecast_metrics = json.loads(metrics_p.read_text(encoding="utf-8"))
            except Exception:
                self.forecast_metrics = {}

    def _init_or_load_action_records(self) -> None:
        """Initialize or load persistent intervention action records from disk."""
        if self.records_path is not None and self.records_path.exists():
            try:
                content = self.records_path.read_text(encoding="utf-8")
                records = json.loads(content)
                if (isinstance(records, list) and len(records) > 0
                        and records[0].get("record_version") == RECORD_VERSION):
                    self.action_records = records
                    return
            except Exception:
                pass

        # Build initial records from source datasets
        if self.interventions_df is None or self.interventions_df.empty:
            self.action_records = []
            return

        idf = self.interventions_df.copy()
        odf = self.outcomes_df.copy() if self.outcomes_df is not None else pd.DataFrame()
        adf = self.assessments_df.copy() if self.assessments_df is not None else pd.DataFrame()

        # Merge interventions with outcomes
        merged = idf.merge(
            odf[["intervention_id", "baseline_cbi_work_score", "follow_up_cbi_work_score", "observed_change", "follow_up_observed"]],
            on="intervention_id",
            how="left"
        ) if not odf.empty else idf.copy()

        # Merge baseline assessment context
        first_assessments: Dict[str, Dict[str, Any]] = {}
        if not adf.empty:
            sorted_adf = _chronological(adf)
            for _, arow in sorted_adf.iterrows():
                eid = str(arow.get("employee_id", ""))
                if eid not in first_assessments:
                    first_assessments[eid] = {
                        "department": str(arow.get("department", "General")),
                        "role_type": str(arow.get("role_type", "individual_contributor")),
                        "assessment_date": str(arow.get("assessment_date", "")),
                        "overtime_hours": float(arow.get("overtime_hours_per_week", 0.0)) if pd.notna(arow.get("overtime_hours_per_week")) else 0.0,
                        "meeting_hours": float(arow.get("meeting_hours_per_week", 0.0)) if pd.notna(arow.get("meeting_hours_per_week")) else 0.0,
                        "stress_level": float(arow.get("stress_level_0_10", 0.0)) if pd.notna(arow.get("stress_level_0_10")) else 0.0,
                        "sleep_hours": float(arow.get("sleep_hours_avg", 7.0)) if pd.notna(arow.get("sleep_hours_avg")) else 7.0,
                    }

        def _map_owner(dept: str) -> str:
            d = dept.lower()
            if "eng" in d: return "Engineering People Ops"
            if "ops" in d: return "Workforce Operations Lead"
            if "sales" in d or "sal" in d: return "Sales Wellbeing Partner"
            if "mkt" in d or "market" in d: return "Marketing Talent Partner"
            if "hr" in d or "human" in d: return "People Advisory Group"
            if "fin" in d: return "Finance Operations Lead"
            return "Central People Partner"

        def _map_suggested_action(itype: str) -> str:
            t = str(itype).lower()
            if "workload" in t:
                return "Conduct workload audit and rebalance non-critical deliverables."
            if "schedule" in t:
                return "Implement core hours guardrails and designated focus time blocks."
            if "workshop" in t:
                return "Enroll in cognitive recovery workshop with peer group coaching."
            if "eap" in t or "counsel" in t:
                return "Offer confidential 1:1 professional Employee Assistance counseling."
            if "control" in t or "waitlist" in t:
                return "Enrolled in randomized pilot control arm; monitoring routine metrics."
            return "Review role workload drivers with people manager."

        # Baseline, follow-up, outcome and forecast all come from the loop (verified against raw monthly scores)
        linked = self.loop.linked.set_index("intervention_id") if self.loop is not None else pd.DataFrame()
        forecasts: Dict[tuple, float] = {}
        if self.loop is not None:
            rec = self.loop.records
            keys = set(zip(idf["employee_id"], idf["referral_period"]))
            at_ref = rec[np.array([k in keys for k in zip(rec["employee_id"], rec["period"])])
                         & rec["cbi_work_score"].notna().to_numpy()]
            if len(at_ref):
                forecasts = dict(zip(zip(at_ref["employee_id"], at_ref["period"]),
                                     self.loop.model.predict_mean(at_ref).round(1)))

        records = []
        for _, row in merged.iterrows():
            iid = str(row.get("intervention_id", ""))
            eid = str(row.get("employee_id", ""))
            raw_itype = str(row.get("intervention_type", "workload_review"))
            clean_itype = raw_itype.replace("_", " ").title()
            comp_status = str(row.get("completion_status", "planned")).lower()

            # Map raw status to workflow action status
            if comp_status == "completed":
                action_status = "completed"
            elif comp_status == "in_progress":
                action_status = "in_progress"
            elif comp_status == "planned":
                action_status = "proposed"
            elif comp_status == "not_completed":
                action_status = "declined"
            elif comp_status == "not_applicable":
                action_status = "waitlist_control"
            else:
                action_status = "proposed"

            context = first_assessments.get(eid, {})
            dept = context.get("department", "Workforce Operations")
            role_type = context.get("role_type", "individual_contributor").replace("_", " ").title()

            lk = linked.loc[iid] if iid in linked.index else {}
            def _num(key):
                v = lk.get(key) if len(lk) else None
                return float(v) if v is not None and pd.notna(v) else None
            base = _num("baseline_score")
            base_score = base if base is not None else float("nan")
            follow_score = _num("follow_up_score")
            obs_change = _num("observed_change")
            fo_observed = follow_score is not None
            outcome = OUTCOME_LABELS.get(lk.get("outcome") if len(lk) else None, "insufficient_data")

            # Derive risk drivers
            drivers = []
            if context.get("overtime_hours", 0) >= 5.0:
                drivers.append(f"Overtime: {round(context['overtime_hours'], 1)}h/wk")
            if context.get("meeting_hours", 0) >= 10.0:
                drivers.append(f"Meeting Load: {round(context['meeting_hours'], 1)}h/wk")
            if context.get("stress_level", 0) >= 6.0:
                drivers.append(f"High Stress: {round(context['stress_level'], 1)}/10")
            if base_score >= 50.0:
                drivers.append(f"Elevated CBI Score ({round(base_score, 1)})")
            if not drivers:
                drivers.append("Workload Drift")

            # Risk band
            if base is None:
                risk_band = "No baseline score"
            elif base_score >= 50.0:
                risk_band = "Elevated"
            elif base_score >= 35.0:
                risk_band = "Moderate"
            else:
                risk_band = "Low"

            # Next-month forecast from the loop's model, made at the referral month (None if no score then)
            forecast_score = forecasts.get((eid, str(row.get("referral_period", ""))))

            records.append({
                "action_id": iid,
                "employee_id": eid,
                "department": dept,
                "role_type": role_type,
                "baseline_period": str(row.get("referral_period", "2025-01")),
                "baseline_date": context.get("assessment_date") or _date(row.get("referral_period")),
                "record_version": RECORD_VERSION,
                "baseline_cbi_score": round(base_score, 1) if base is not None else None,
                "forecast_cbi_score": forecast_score,
                "risk_band": risk_band,
                "risk_drivers": drivers,
                "intervention_type": clean_itype,
                "referral_reason": str(row.get("referral_reason", "High Burnout Indicator")).replace("_", " ").title(),
                "suggested_action": _map_suggested_action(raw_itype),
                "action_status": action_status,
                "responsible_owner": (str(row.get("owner")).strip() if pd.notna(row.get("owner")) and str(row.get("owner")).strip()
                                      else _map_owner(dept)),
                "start_date": _date(row.get("start_date")),
                "completed_date": _date(row.get("planned_end_date")) if action_status == "completed" else "—",
                # waitlist controls have no end date; their follow-up is due 3 months after referral
                "follow_up_due_date": (_date(row.get("planned_end_date")) if pd.notna(row.get("planned_end_date"))
                                       else str(lk.get("follow_up_period", "—")) if len(lk) else "—"),
                "follow_up_assessment_date": (str(lk.get("follow_up_score_period")) if fo_observed else None),
                "follow_up_cbi_score": round(follow_score, 1) if follow_score is not None else None,
                "observed_change": round(obs_change, 1) if obs_change is not None else None,
                "outcome_status": outcome,
                "trial_arm": str(row.get("trial_arm", "")),
                "notes": (str(row.get("notes")) if pd.notna(row.get("notes")) and str(row.get("notes")).strip()
                          else "Initial referral logged from quarterly wellbeing survey."),
                "logged_here": iid.startswith(LOGGED_PREFIX),
            })

        self.action_records = records
        self.save_action_records()

    def save_action_records(self) -> None:
        """Save persistent intervention records to disk (never for uploaded data)."""
        if self.records_path is None:
            return
        try:
            self.records_path.parent.mkdir(parents=True, exist_ok=True)
            self.records_path.write_text(json.dumps(self.action_records, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_action_records(
        self,
        status: Optional[str] = None,
        department: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
        sort_by: str = "priority"
    ) -> Dict[str, Any]:
        """Query persistent action records with filtering, search, and pagination."""
        records = self.action_records

        # Calculate counts across all records
        status_counts = {
            "all": len(records),
            "proposed": sum(1 for r in records if r["action_status"] == "proposed"),
            "accepted": sum(1 for r in records if r["action_status"] == "accepted"),
            "in_progress": sum(1 for r in records if r["action_status"] == "in_progress"),
            "completed": sum(1 for r in records if r["action_status"] == "completed"),
            "declined": sum(1 for r in records if r["action_status"] == "declined"),
            "waitlist_control": sum(1 for r in records if r["action_status"] == "waitlist_control"),
        }

        # Available departments
        departments = sorted(list(set(r["department"] for r in records if r.get("department"))))

        # Filtering
        filtered = records
        if status and status.lower() != "all":
            st = status.lower()
            filtered = [r for r in filtered if r["action_status"].lower() == st]

        if department and department.lower() != "all":
            d = department.lower()
            filtered = [r for r in filtered if r["department"].lower() == d]

        if search:
            q = search.lower().strip()
            filtered = [
                r for r in filtered
                if q in r["employee_id"].lower()
                or q in r["action_id"].lower()
                or q in r.get("responsible_owner", "").lower()
                or q in r.get("intervention_type", "").lower()
            ]

        # Sorting
        if sort_by == "priority":
            # Elevated first, then baseline score desc
            band_order = {"Elevated": 3, "Moderate": 2, "Low": 1}
            filtered.sort(key=lambda r: (-band_order.get(r.get("risk_band", "Low"), 0), -(r.get("baseline_cbi_score") or 0)))
        elif sort_by == "score_desc":
            filtered.sort(key=lambda r: -(r.get("baseline_cbi_score") or 0))
        elif sort_by == "score_asc":
            filtered.sort(key=lambda r: (r.get("baseline_cbi_score") or 0))
        elif sort_by == "date_desc":
            filtered.sort(key=lambda r: str(r.get("start_date", "")), reverse=True)

        total_filtered = len(filtered)
        total_pages = max(1, math.ceil(total_filtered / page_size)) if page_size > 0 else 1
        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = start_idx + page_size
        paginated = filtered[start_idx:end_idx]

        return {
            "records": paginated,
            "total_filtered": total_filtered,
            "total_count": len(records),
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "status_counts": status_counts,
            "departments": departments,
        }

    def update_action_status(
        self,
        action_id: str,
        status: Optional[str] = None,
        owner: Optional[str] = None,
        follow_up_due_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an action record's status, owner, follow-up date, and notes with disk persistence."""
        aid = str(action_id).strip().lower()
        matched: Optional[Dict[str, Any]] = None
        for r in self.action_records:
            if r["action_id"].lower() == aid or r["employee_id"].lower() == aid:
                matched = r
                break

        if matched is None:
            return None

        if status:
            valid_statuses = {"proposed", "accepted", "in_progress", "completed", "declined"}
            clean_status = status.strip().lower()
            if clean_status in valid_statuses:
                matched["action_status"] = clean_status
                if clean_status == "completed" and (not matched.get("completed_date") or matched["completed_date"] == "—"):
                    matched["completed_date"] = time.strftime("%Y-%m-%d", time.gmtime())
        if owner:
            matched["responsible_owner"] = str(owner).strip()
        if follow_up_due_date:
            matched["follow_up_due_date"] = str(follow_up_due_date).strip()
        if notes:
            matched["notes"] = str(notes).strip()

        self.save_action_records()
        return matched

    def record_new_intervention(
        self,
        employee_id: str,
        intervention_type: str,
        owner: Optional[str] = None,
        follow_up_due_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a newly agreed supportive intervention for an employee."""
        eid = str(employee_id).strip().upper()
        clean_itype = str(intervention_type).replace("_", " ").title()

        # Generate action_id
        max_id = 1046
        for r in self.action_records:
            try:
                num = int(r["action_id"].replace("INT-", ""))
                if num > max_id:
                    max_id = num
            except Exception:
                pass
        next_id = f"INT-{max_id + 1:05d}"

        # Match baseline info if employee exists in assessments
        base_score = 45.0
        dept = "Workforce Operations"
        role_type = "Individual Contributor"
        if self.assessments_df is not None:
            m = self.assessments_df[self.assessments_df["employee_id"].astype(str).str.upper() == eid]
            if not m.empty:
                last_row = _chronological(m).iloc[-1]
                base_score = float(last_row.get("cbi_work_score", 45.0))
                dept = str(last_row.get("department", dept))
                role_type = str(last_row.get("role_type", role_type)).replace("_", " ").title()

        risk_band = "Elevated" if base_score >= 50.0 else ("Moderate" if base_score >= 35.0 else "Low")
        today_str = time.strftime("%Y-%m-%d", time.gmtime())

        new_record = {
            "action_id": next_id,
            "employee_id": eid,
            "department": dept,
            "role_type": role_type,
            "baseline_period": time.strftime("%Y-%m", time.gmtime()),
            "baseline_date": today_str,
            "baseline_cbi_score": round(base_score, 1),
            "forecast_cbi_score": round(base_score + 2.0, 1),
            "risk_band": risk_band,
            "risk_drivers": ["Proactive Intervention Referral"],
            "intervention_type": clean_itype,
            "referral_reason": "Workplace Support Program",
            "suggested_action": f"Initiate supportive {clean_itype} plan with manager alignment.",
            "action_status": "accepted",
            "responsible_owner": str(owner).strip() if owner else "People Operations",
            "start_date": today_str,
            "completed_date": "—",
            "follow_up_due_date": str(follow_up_due_date).strip() if follow_up_due_date else "2026-03-31",
            "follow_up_assessment_date": None,
            "follow_up_cbi_score": None,
            "observed_change": None,
            "outcome_status": "insufficient_data",
            "trial_arm": "",
            "notes": str(notes).strip() if notes else "Action recorded via Intervention Command Center.",
        }

        self.action_records.insert(0, new_record)
        self.save_action_records()
        return new_record

    def record_followup_assessment(
        self,
        action_id: str,
        follow_up_cbi_score: float,
        assessment_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a subsequent assessment for an action record and recompute longitudinal outcome."""
        aid = str(action_id).strip().lower()
        matched: Optional[Dict[str, Any]] = None
        for r in self.action_records:
            if r["action_id"].lower() == aid or r["employee_id"].lower() == aid:
                matched = r
                break

        if matched is None:
            return None

        score = round(max(0.0, min(100.0, float(follow_up_cbi_score))), 1)
        matched["follow_up_cbi_score"] = score
        matched["follow_up_assessment_date"] = str(assessment_date).strip() if assessment_date else time.strftime("%Y-%m-%d", time.gmtime())

        base_score = float(matched.get("baseline_cbi_score", score))
        change = round(score - base_score, 1)
        matched["observed_change"] = change
        matched["outcome_status"] = classify_outcome_status(True, change)

        if notes:
            matched["notes"] = f"{matched.get('notes', '')} | Follow-up logged: {notes}".strip(" |")

        self.save_action_records()
        return matched

    @property
    def has_longitudinal_data(self) -> bool:
        return self.assessments_df is not None and not self.assessments_df.empty

    @property
    def has_interventions_data(self) -> bool:
        return bool(self.action_records) or (self.interventions_df is not None and not self.interventions_df.empty)

    def get_historical_trend(self) -> List[Dict[str, Any]]:
        """Compute monthly historical burnout trend with counts and level distributions."""
        if not self.has_longitudinal_data or self.assessments_df is None:
            return []

        df = self.assessments_df
        results = []
        for period, grp in df.groupby("period", sort=True):
            scores = grp["cbi_work_score"].dropna()
            if scores.empty:
                continue
            mean_cbi = round(float(scores.mean()), 2)
            total_scored = len(scores)
            low_cnt = int((scores < 35.0).sum())
            mod_cnt = int(((scores >= 35.0) & (scores < 50.0)).sum())
            elev_cnt = int((scores >= 50.0).sum())
            results.append({
                "period": str(period),
                "mean_cbi_score": mean_cbi,
                "norm_score_10": round(mean_cbi / 10.0, 2),
                "assessment_count": total_scored,
                "mean_hours": round(float(grp["work_hours_per_week"].mean()), 1) if "work_hours_per_week" in grp else 40.0,
                "mean_overtime": round(float(grp["overtime_hours_per_week"].mean()), 1) if "overtime_hours_per_week" in grp else 0.0,
                "levels": {
                    "low": low_cnt,
                    "moderate": mod_cnt,
                    "elevated": elev_cnt,
                    "elevated_rate": round(elev_cnt / total_scored * 100.0, 1) if total_scored else 0.0,
                }
            })
        return results

    @_locked
    def get_forecast_payload(self, cohort: Optional[str] = None) -> Dict[str, Any]:
        """Held-out monthly forecasts and next-month projection, computed by the burnoutiq loop."""
        if self.loop is None:
            return {"available": False, "message": "Longitudinal forecasting dataset is not available."}
        return self._label(forecast_payload(self.loop, cohort), "synthetic_notice")

    @_locked
    def get_loop_payload(self, period: Optional[str] = None) -> Dict[str, Any]:
        """Every stage of the Assess -> Predict -> Simulate -> Intervene -> Verify loop for one month."""
        if self.loop is None:
            return {"available": False, "message": "Longitudinal panel is not available."}
        return self._label(loop_payload(self.loop, period), "notice")

    def _label(self, payload: Dict[str, Any], notice_key: str) -> Dict[str, Any]:
        """Say which data the numbers come from; uploaded data is not the synthetic demo panel."""
        payload["source"] = self.source
        if self.loop is not None:
            payload["periods"] = self.loop.periods
            if notice_key == "notice":
                payload["check"] = self.predicted_vs_actual(payload.get("period") or self.loop.periods[-1])
                eff = {e["intervention_type"]: e for e in payload.get("effects") or []}
                payload["support_types"] = [{"type": t, "evidence": eff.get(t, {}).get("evidence", "no data yet"),
                                             "simulation_effect": eff.get(t, {}).get("simulation_effect")}
                                            for t in SUPPORT_TYPES]
        if self.source.get("kind") == "upload":
            payload[notice_key] = (f"Computed from {self.source['name']}. "
                                   "Observed changes are not causal effects.")
        return payload

    def get_interventions_payload(self) -> Dict[str, Any]:
        """Produce verified intervention lifecycle tracking, outcome distributions, and review queue."""
        records = self.action_records
        total_int = len(records)
        if total_int == 0:
            return {
                "available": False,
                "message": "Intervention tracking records are not available."
            }

        # Lifecycle counts
        completed = sum(1 for r in records if r["action_status"] == "completed")
        in_progress = sum(1 for r in records if r["action_status"] == "in_progress")
        proposed = sum(1 for r in records if r["action_status"] == "proposed")
        accepted = sum(1 for r in records if r["action_status"] == "accepted")
        declined = sum(1 for r in records if r["action_status"] == "declined")
        waitlist_cnt = sum(1 for r in records if r["action_status"] == "waitlist_control")

        # Active intervention assignments (excluding waitlist control arm)
        active_assignments = total_int - waitlist_cnt

        # Reassessments
        reassessed = [r for r in records if r.get("follow_up_cbi_score") is not None and r.get("outcome_status") != "insufficient_data"]
        follow_up_reassessed = len(reassessed)
        improving_cnt = sum(1 for r in reassessed if r["outcome_status"] == "improving")
        stable_cnt = sum(1 for r in reassessed if r["outcome_status"] == "stable")
        worsening_cnt = sum(1 for r in reassessed if r["outcome_status"] == "worsening")

        # Preserved backward-compatible funnel structure
        funnel = {
            "recommended": total_int,
            "accepted_or_planned": active_assignments,
            "implemented_or_completed": completed,
            "reassessed_followup": follow_up_reassessed,
        }

        # Rigorous, clarified dual-track lifecycles
        execution_lifecycle = {
            "cohort_total": total_int,
            "active_assignments": active_assignments,
            "waitlist_control": waitlist_cnt,
            "completed": completed,
            "completed_rate_pct": round(completed / active_assignments * 100.0, 1) if active_assignments else 0.0,
            "in_progress": in_progress,
            "in_progress_rate_pct": round(in_progress / active_assignments * 100.0, 1) if active_assignments else 0.0,
            "declined_or_discontinued": declined,
            "declined_rate_pct": round(declined / active_assignments * 100.0, 1) if active_assignments else 0.0,
            "proposed_or_planned": proposed + accepted,
            "proposed_rate_pct": round((proposed + accepted) / active_assignments * 100.0, 1) if active_assignments else 0.0,
        }

        reassessment_lifecycle = {
            "scheduled_cohort": total_int,
            "follow_up_completed": follow_up_reassessed,
            "coverage_rate_pct": round(follow_up_reassessed / total_int * 100.0, 1) if total_int else 0.0,
            "follow_up_missed_or_pending": total_int - follow_up_reassessed,
            "improving": improving_cnt,
            "improving_pct": round(improving_cnt / follow_up_reassessed * 100.0, 1) if follow_up_reassessed else 0.0,
            "stable": stable_cnt,
            "stable_pct": round(stable_cnt / follow_up_reassessed * 100.0, 1) if follow_up_reassessed else 0.0,
            "worsening": worsening_cnt,
            "worsening_pct": round(worsening_cnt / follow_up_reassessed * 100.0, 1) if follow_up_reassessed else 0.0,
        }

        by_status = {s: sum(1 for r in reassessed if r["action_status"] == s)
                     for s in ("completed", "declined", "waitlist_control")}
        funnel_clarification = (
            f"Follow-up scores ({follow_up_reassessed}) are counted separately from completed interventions ({completed}): "
            f"{by_status['completed']} follow-ups come from completed interventions, {by_status['declined']} from "
            f"discontinued ones and {by_status['waitlist_control']} from waitlist controls. "
            f"{completed} of {active_assignments} active assignments were completed ({waitlist_cnt} waitlist controls excluded)."
        )

        # Breakdown by intervention modality
        outcome_by_type: Dict[str, Dict[str, int]] = {}
        type_groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            itype = r.get("intervention_type", "General")
            type_groups.setdefault(itype, []).append(r)

        for itype, group in type_groups.items():
            outcome_by_type[itype] = {
                "improving": sum(1 for r in group if r["outcome_status"] == "improving"),
                "stable": sum(1 for r in group if r["outcome_status"] == "stable"),
                "worsening": sum(1 for r in group if r["outcome_status"] == "worsening"),
                "insufficient_data": sum(1 for r in group if r["outcome_status"] == "insufficient_data"),
                "total": len(group),
            }

        # Sample records for display
        sample_records = [
            {
                "action_id": r["action_id"],
                "intervention_id": r["action_id"],
                "employee_id": r["employee_id"],
                "department": r.get("department", "—"),
                "intervention_type": r["intervention_type"],
                "action_status": r["action_status"],
                "completion_status": r["action_status"].replace("_", " ").title(),
                "responsible_owner": r.get("responsible_owner", "People Partner"),
                "start_date": r.get("start_date", "—"),
                "planned_end_date": r.get("follow_up_due_date", "—"),
                "baseline_cbi_score": r.get("baseline_cbi_score"),
                "follow_up_cbi_score": r.get("follow_up_cbi_score"),
                "observed_change": r.get("observed_change"),
                "outcome_status": r.get("outcome_status", "insufficient_data"),
                "risk_band": r.get("risk_band", "Moderate"),
                "risk_drivers": r.get("risk_drivers", []),
                "notes": r.get("notes", ""),
            }
            for r in records[:40]
        ]

        return {
            "available": True,
            "total_interventions": total_int,
            "completion_status_counts": {
                "completed": completed,
                "not_completed": declined,
                "in_progress": in_progress,
                "planned": proposed + accepted,
                "not_applicable": waitlist_cnt,
            },
            "funnel": funnel,
            "execution_lifecycle": execution_lifecycle,
            "reassessment_lifecycle": reassessment_lifecycle,
            "funnel_clarification": funnel_clarification,
            "follow_up_coverage_rate": round(follow_up_reassessed / total_int * 100.0, 1) if total_int else 0.0,
            "completion_rate": round(completed / total_int * 100.0, 1) if total_int else 0.0,
            "outcome_by_type": outcome_by_type,
            "sample_records": sample_records,
            "action_counts": {
                "proposed": proposed,
                "accepted": accepted,
                "in_progress": in_progress,
                "completed": completed,
                "declined": declined,
                "total": total_int,
            },
            "non_causal_disclaimer": NON_CAUSAL_DISCLAIMER,
            "data_origin": SYNTHETIC_DATA_LABEL,
        }

    def get_employee_longitudinal_profile(self, employee_id: str) -> Optional[Dict[str, Any]]:
        """Look up dated timeline of assessments, linked intervention events, and forecast for an employee."""
        emp_id = str(employee_id).strip().upper()
        if not self.has_longitudinal_data or self.assessments_df is None:
            return None

        df = self.assessments_df
        match = _chronological(df[df["employee_id"].astype(str).str.strip().str.upper() == emp_id])
        if match.empty:
            return None

        timeline = []
        for _, row in match.iterrows():
            timeline.append({
                "period": str(row.get("period", "")),
                "assessment_date": str(row.get("assessment_date", "")),
                "cbi_work_score": round(float(row.get("cbi_work_score", 0)), 1) if pd.notna(row.get("cbi_work_score")) else None,
                "norm_score_10": round(float(row.get("cbi_work_score", 0)) / 10.0, 2) if pd.notna(row.get("cbi_work_score")) else None,
                "work_hours": round(float(row.get("work_hours_per_week", 0)), 1) if pd.notna(row.get("work_hours_per_week")) else None,
                "overtime_hours": round(float(row.get("overtime_hours_per_week", 0)), 1) if pd.notna(row.get("overtime_hours_per_week")) else None,
                "meetings_per_week": round(float(row.get("meeting_hours_per_week", 0)), 1) if pd.notna(row.get("meeting_hours_per_week")) else None,
                "stress_level": round(float(row.get("stress_level_0_10", 0)), 1) if pd.notna(row.get("stress_level_0_10")) else None,
                "intervention_active": bool(row.get("intervention_active", False)),
            })

        # Linked intervention records from persistent action store
        linked_interventions = [
            r for r in self.action_records
            if r["employee_id"].upper() == emp_id
        ]

        loop_view = self.loop.employee(str(match["employee_id"].iat[0])) if self.loop is not None else None
        standing = None
        if loop_view and loop_view.get("items"):
            # where this person stands in their latest scored month: own score vs department and company averages
            period = loop_view["items"]["period"]
            rows = self.loop.run(period).employees
            me = rows[rows["employee_id"] == str(match["employee_id"].iat[0])]
            dept = me["department"].iat[0] if len(me) else None
            in_dept = rows[rows["department"] == dept]["cbi_work_score"].dropna()
            standing = {"period": period, "score": float(me["cbi_work_score"].iat[0]) if len(me) and pd.notna(me["cbi_work_score"].iat[0]) else None,
                        "department": dept,
                        "department_mean": round(float(in_dept.mean()), 1) if len(in_dept) >= 5 else None,
                        "company_mean": round(float(rows["cbi_work_score"].mean()), 1),
                        "reference_mean": self.loop.norm.get("mean")}
        return {
            "employee_id": emp_id,
            "is_longitudinal": True,
            "assessment_count": len(timeline),
            "timeline": timeline,
            "linked_interventions": linked_interventions,
            "forecast": loop_view["forecast"] if loop_view else None,
            "scenarios": loop_view["scenarios"] if loop_view else {},
            "items": loop_view["items"] if loop_view else None,
            "contracted_hours": loop_view["contracted_hours"] if loop_view else None,
            "standing": standing,
            "scenario_note": "Model-based scenarios (10th-90th percentile of 500 simulated paths); intervention "
                             "effects labelled by evidence level in /api/loop effects. Not a promise.",
            "disclaimer": NON_CAUSAL_DISCLAIMER,
        }
