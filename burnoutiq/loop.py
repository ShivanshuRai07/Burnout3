"""The BurnoutIQ loop: one object that runs every stage on a company's three input files.

    loop = BurnoutLoop.from_csv(employees, monthly, interventions).fit()
    result = loop.run("2025-12")       # employee table, division table, company summary, effects
    profile = loop.employee("SYN-00017")  # history, forecast, simulated scenarios, support and outcomes
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from burnoutiq import assess, intervene, learn, reference, simulate, trajectory
from burnoutiq.predict import ForecastModel
from burnoutiq.schema import Inputs, read_csvs, validate
from burnoutiq.verify import reliable_change_threshold

CONTEXT = ["department", "team_id", "role_type", "work_mode", "contracted_hours_per_week"]


@dataclass
class LoopResult:
    period: str
    employees: pd.DataFrame
    divisions: pd.DataFrame
    company: dict
    effects: pd.DataFrame
    randomised: dict | None
    interventions: pd.DataFrame
    forecast_metrics: dict
    calibration: pd.DataFrame
    issues: list[str] = field(default_factory=list)

    def save(self, folder: str | Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.employees.to_csv(folder / "employees_status.csv", index=False)
        self.divisions.to_csv(folder / "divisions.csv", index=False)
        self.effects.to_csv(folder / "intervention_effects.csv", index=False)
        self.interventions.to_csv(folder / "interventions_verified.csv", index=False)
        self.calibration.to_csv(folder / "forecast_calibration.csv", index=False)
        summary = {"period": self.period, "company": self.company, "randomised_pilot": self.randomised,
                   "forecast_metrics": self.forecast_metrics, "input_issues": self.issues}
        (folder / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return folder


class BurnoutLoop:
    def __init__(self, inputs: Inputs, norm: dict = reference.REFERENCE_NORM):
        self.inputs = inputs
        self.norm = norm
        self.model: ForecastModel | None = None
        self.linked = pd.DataFrame()
        self.effects = pd.DataFrame()
        self.randomised: dict | None = None
        self.calibration = pd.DataFrame()
        self._runs: dict[str, LoopResult] = {}

        emp = inputs.employees.set_index("employee_id")
        rec = inputs.monthly.copy()
        for col in CONTEXT:
            if col not in rec.columns and col in emp.columns:
                rec[col] = rec["employee_id"].map(emp[col])
        rec["cbi_work_score"] = assess.score_cbi(rec)
        rec["level"] = assess.level(rec["cbi_work_score"])
        self.records = rec.sort_values(["employee_id", "period"]).reset_index(drop=True)
        self.scores = self.records.loc[self.records["cbi_work_score"].notna(), ["employee_id", "period", "cbi_work_score"]]

        first = self.records[self.records["period"] == self.records["period"].min()]
        self.reliability = assess.cronbach_alpha(self.records)
        self.rci = reliable_change_threshold(float(first["cbi_work_score"].std()), self.reliability)

    @classmethod
    def from_csv(cls, employees, monthly, interventions=None, **kw) -> "BurnoutLoop":
        return cls(read_csvs(employees, monthly, interventions), **kw)

    @classmethod
    def from_frames(cls, employees, monthly, interventions=None, **kw) -> "BurnoutLoop":
        return cls(validate(employees, monthly, interventions), **kw)

    @property
    def periods(self) -> list[str]:
        return sorted(self.records["period"].unique())

    def fit(self) -> "BurnoutLoop":
        self.model = ForecastModel().fit(self.records)
        self.linked = intervene.link_scores(self.inputs.interventions, self.scores, self.rci)
        self.effects = learn.effect_table(self.linked, self.scores) if not self.linked.empty else pd.DataFrame()
        self.randomised = learn.randomised_estimate(self.linked)
        self.calibration = learn.calibration_check(self.model, self.records)
        self._runs = {}
        return self

    def run(self, period: str | None = None) -> LoopResult:
        if self.model is None:
            self.fit()
        period = period or self.periods[-1]
        if period in self._runs:
            return self._runs[period]
        cur = self.records[self.records["period"] == period].copy()
        has_score = cur["cbi_work_score"].notna()
        cur = cur.join(self.model.predict(cur[has_score]))
        flags = reference.employee_flags(cur, self.records)
        # the flag is the trajectory rule (sustained / reliable rise / quiet after high), which beat the
        # single-month reference rule on held-out employees (evaluate_detection.py); the three reference
        # points stay as context for why someone stands out
        tr = trajectory.trajectory_flags(trajectory.history_features(self.records, period), self.rci)
        flags = flags.merge(tr[["employee_id", "prev_score", "prev_period", "missed_streak", "sustained_high",
                                "reliable_rise", "quiet_after_high", "trajectory_level", "trajectory_reasons"]],
                            on="employee_id", how="left")
        flags["reference_flag"] = flags["flagged"]
        flags["context_reasons"] = flags["flag_reasons"]
        flags["flagged"] = flags["trajectory_level"].eq("flagged")
        flags["flag_reasons"] = flags["trajectory_reasons"].fillna("")
        divisions = reference.division_summary(flags, self.norm)
        flags["quadrant"] = reference.quadrant(flags, divisions)
        flags["status"] = flags["employee_id"].map(
            intervene.employee_status(self.inputs.employees, flags, self.linked, period))
        # urgency per department: flagged with no support yet, very high scores, gone quiet after a high score
        urgent = flags.assign(needs_decision=flags["status"].eq("flagged"), very_high=flags["level"].eq("very_high"),
                              gone_quiet=flags["quiet_after_high"].fillna(False).astype(bool))
        counts = urgent.groupby("department")[["needs_decision", "very_high", "gone_quiet"]].sum()
        for col in counts:
            divisions[f"n_{col}"] = divisions["department"].map(counts[col]).fillna(0).astype(int)

        known = self.linked[self.linked["referral_period"] <= period]
        latest = known.sort_values("referral_period").groupby("employee_id").tail(1).set_index("employee_id")
        flags["latest_intervention"] = flags["employee_id"].map(latest["intervention_type"])
        flags["latest_outcome"] = flags["employee_id"].map(
            latest["outcome"].where(latest["follow_up_score_period"].fillna("9999") <= period))

        keep = ["employee_id", "period", "department", "team_id", "role_type", "cbi_work_score", "level",
                "forecast", "forecast_low", "forecast_high", "work_hours_per_week", "overtime_hours_per_week",
                "perceived_workload_1_5", "workload_level", "hours_over_limit", "division_score_z",
                "division_hours_z", "personal_baseline", "personal_change", "flagged", "flag_reasons",
                "trajectory_level", "prev_score", "prev_period", "missed_streak", "reference_flag", "context_reasons",
                "quadrant", "status", "latest_intervention", "latest_outcome"]
        employees = flags.reindex(columns=keep)

        active = self.inputs.employees
        n_active = int(len(cur))
        scored = cur["cbi_work_score"].dropna()
        funnel_iv = known[known["completion_status"] != "not_applicable"]
        due = funnel_iv[funnel_iv["follow_up_period"] <= period]
        company = {
            "period": period, "employees_with_record": n_active, "employees_scored": int(len(scored)),
            "response_rate": round(len(scored) / n_active, 3) if n_active else None,
            "mean_score": round(float(scored.mean()), 1) if len(scored) else None,
            "pct_high": round(100 * float((scored >= assess.HIGH).mean()), 1) if len(scored) else None,
            "reference": self.norm, "n_flagged": int(flags["flagged"].sum()),
            "n_watch": int((flags["trajectory_level"] == "watch").sum()),
            "n_quiet_after_high": int(flags["quiet_after_high"].fillna(False).astype(bool).sum()),
            "quadrants": flags["quadrant"].value_counts().to_dict(),
            "status": flags["status"].value_counts().to_dict(),
            "systemic_divisions": divisions.loc[divisions.get("systemic", pd.Series(dtype=bool)).fillna(False).astype(bool),
                                                "department"].tolist() if "systemic" in divisions else [],
            "interventions": {
                "logged": int(len(funnel_iv)),
                "completed": int((funnel_iv["completion_status"] == "completed").sum()),
                "follow_up_due_by_now": int(len(due)),
                "followed_up": int(due["follow_up_score"].notna().sum()),
                "improved": int((due["outcome"] == "improved").sum()),
                "no_change": int((due["outcome"] == "no_change").sum()),
                "worsened": int((due["outcome"] == "worsened").sum()),
            },
            "reliable_change_threshold": round(self.rci, 1), "cbi_reliability_alpha": round(self.reliability, 3),
            "employees_total": int(len(active)),
        }
        result = LoopResult(period, employees, divisions, company, self.effects, self.randomised, self.linked,
                            self.model.metrics, self.calibration, list(self.inputs.issues))
        self._runs[period] = result
        return result

    def employee(self, employee_id: str, months: int = 3) -> dict | None:
        hist = self.records[self.records["employee_id"] == employee_id]
        if hist.empty:
            return None
        cols = ["period", "cbi_work_score", "level", "work_hours_per_week", "overtime_hours_per_week"]
        history = hist.reindex(columns=cols)
        last = hist[hist["cbi_work_score"].notna()].tail(1)
        out = {"employee_id": employee_id, "history": history.to_dict("records"),
               "interventions": self.linked[self.linked["employee_id"] == employee_id].to_dict("records"),
               "forecast": None, "scenarios": {}, "items": None,
               "contracted_hours": None if "contracted_hours_per_week" not in hist or hist["contracted_hours_per_week"].isna().all()
               else float(hist["contracted_hours_per_week"].dropna().iat[-1])}
        if not last.empty:
            out["items"] = {"period": last["period"].iat[0], "answers": assess.item_scores(last.iloc[0])}
        if not last.empty and self.model is not None:
            out["forecast"] = {"from_period": last["period"].iat[0], **self.model.predict(last).iloc[0].to_dict()}
            scen = simulate.scenarios(self.model, last.iloc[0], self.effects, months,
                                      extra={"overtime_minus_5h": {"overtime_hours_per_week": -5,
                                                                   "work_hours_per_week": -5}})
            out["scenarios"] = {k: v.to_dict("records") for k, v in scen.items()}
        return out

    def save_model(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"forecast": self.model, "effects": self.effects, "rci": self.rci,
                     "reliability": self.reliability, "norm": self.norm}, path)
        return path
