"""Turn BurnoutLoop results into dashboard payloads. Every number shown comes from here; nothing is typed in."""
from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from burnoutiq import BurnoutLoop
from burnoutiq.predict import transition_pairs

DRIVERS = {
    "overtime_hours_per_week": ("overtime", "h/week"),
    "work_hours_per_week": ("working hours", "h/week"),
    "meeting_hours_per_week": ("meeting hours", "h/week"),
    "after_hours_messages_per_week": ("after-hours messages", "/week"),
    "manager_support_1_5": ("manager support", "/5"),
    "job_control_1_5": ("job control", "/5"),
    "perceived_workload_1_5": ("perceived workload", "/5"),
}

STAGES = [
    {"id": "assess", "name": "Assess", "what": "Score the monthly CBI survey (0-100) and assign a level",
     "rule": "under 50 normal, 50-64 high, 65+ very high (conventional threshold, not a diagnosis)"},
    {"id": "predict", "name": "Predict", "what": "Forecast next month's score with a 95% range",
     "rule": "flag if forecast >= 50 or rising >= 10 points"},
    {"id": "simulate", "name": "Simulate", "what": "Project 3 months ahead with and without changes",
     "rule": "fan of paths; intervention effects come from the learning stage, labelled by evidence level"},
    {"id": "intervene", "name": "Intervene", "what": "A person records the support given",
     "rule": "the model only flags and suggests; a named owner decides"},
    {"id": "verify", "name": "Verify", "what": "Compare follow-up with baseline score",
     "rule": "change <= -5 improved, >= +5 worsened, otherwise no change; reliable only beyond the RCI threshold"},
    {"id": "learn", "name": "Learn (quarterly)", "what": "Compare each intervention type with a matched comparison group "
                                                          "and check forecast calibration", "rule": "observational unless randomised"},
]


MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _csv_bytes(payload: bytes, label: str) -> bytes:
    """Accept raw or gzip-compressed CSV data, with a bounded expanded size."""
    try:
        raw = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
    except OSError as exc:
        raise ValueError(f"{label} could not be unpacked as a gzip CSV: {exc}") from exc
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{label} is larger than 50 MB after decompression.")
    return raw


def upload_to_tracker(tracker, files: Dict[str, bytes]) -> Dict[str, Any]:
    """Run the loop on uploaded CSV bytes (keys: employees, monthly, optional interventions).

    Returns {"ok": True, "source": ...} or {"ok": False, "error": ...}; used by both servers.
    """
    import io

    from burnoutiq.schema import InputError

    if sum(len(b) for b in files.values()) > MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "Files are larger than 50 MB in total."}
    if not files.get("employees") or not files.get("monthly"):
        return {"ok": False, "error": "employees.csv and monthly.csv are required."}
    try:
        frames = {k: pd.read_csv(io.BytesIO(_csv_bytes(v, k))) for k, v in files.items() if v}
    except Exception as exc:
        return {"ok": False, "error": f"Could not read a file as CSV: {exc}"}
    try:
        source = tracker.load_upload(frames["employees"], frames["monthly"], frames.get("interventions"))
    except (InputError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "source": source}


def add_month_to_tracker(tracker, files: Dict[str, bytes]) -> Dict[str, Any]:
    """Append an uploaded monthly.csv (plus optional interventions/employees updates) and rerun the loop."""
    import io

    from burnoutiq.schema import InputError

    if sum(len(b) for b in files.values()) > MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "Files are larger than 50 MB in total."}
    if not files.get("monthly"):
        return {"ok": False, "error": "monthly.csv for the new month is required."}
    try:
        frames = {k: pd.read_csv(io.BytesIO(_csv_bytes(v, k))) for k, v in files.items() if v}
        source = tracker.add_month(frames["monthly"], frames.get("interventions"), frames.get("employees"))
    except (InputError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # unreadable CSV
        return {"ok": False, "error": f"Could not read a file as CSV: {exc}"}
    return {"ok": True, "source": source}


def support_action(tracker, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/loop/support (log) and /api/loop/support/status (started / completed / stopped)."""
    try:
        if path.endswith("/status"):
            return {"ok": True, "support": tracker.update_support(str(body.get("intervention_id", "")), str(body.get("status", "")))}
        return {"ok": True, "support": tracker.log_support(
            str(body.get("employee_id", "")).strip(), str(body.get("intervention_type", "")), str(body.get("owner", "")),
            str(body.get("start_date", "")), str(body.get("planned_end_date", "")), str(body.get("notes", "")))}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def run_tracker_action(action) -> Dict[str, Any]:
    """Call a tracker method that raises ValueError for user errors; wrap the result for the API."""
    try:
        return {"ok": True, "source": action()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def employee_query(tracker, get) -> Dict[str, Any]:
    """Parse query parameters (get(name, default)) for the ranked employee list."""
    try:
        page, size = int(get("page", "0") or 0), int(get("page_size", "25") or 25)
    except ValueError:
        page, size = 0, 25
    return tracker.employee_rows(period=get("period", "") or None, department=get("department", ""),
                                 team=get("team", ""), level=get("level", ""), workload=get("workload", ""),
                                 status=get("status", ""), flagged=get("flagged", "") in ("1", "true"),
                                 query=get("q", ""), sort=get("sort", "score"), page=page, page_size=size,
                                 quadrant=get("quadrant", ""))


def try_survey_action(tracker, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST body: {answers: {cbi_w1..cbi_w7: 0/25/50/75/100}, hours, department} -> score and forecast by hours."""
    try:
        hours = float(body.get("hours", 40))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Hours must be a number."}
    try:
        return tracker.try_survey(body.get("answers") or {}, hours, str(body.get("department") or ""))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def build_loop(data_dir: Path) -> Optional[BurnoutLoop]:
    files = [data_dir / f for f in ("employees.csv", "assessments.csv", "interventions.csv")]
    if not all(p.exists() for p in files):
        return None
    return BurnoutLoop.from_csv(*files).fit()


def _fmt(x: float, nd: int = 1) -> str:
    return f"{x:+.{nd}f}"


def drivers(current: pd.DataFrame, flags: pd.DataFrame) -> list[dict]:
    """Largest standardised differences between flagged and other employees (association, not cause)."""
    df = current.merge(flags[["employee_id", "flagged"]], on="employee_id")
    out = []
    for col, (label, unit) in DRIVERS.items():
        if col not in df or df[col].notna().sum() < 20:
            continue
        a, b = df.loc[df["flagged"], col].dropna(), df.loc[~df["flagged"], col].dropna()
        sd = df[col].std()
        if len(a) < 5 or len(b) < 5 or not sd:
            continue
        out.append({"feature": col, "label": label, "unit": unit, "flagged_mean": round(a.mean(), 1),
                    "others_mean": round(b.mean(), 1), "difference": round(a.mean() - b.mean(), 1),
                    "std_difference": round((a.mean() - b.mean()) / sd, 2)})
    return sorted(out, key=lambda d: -abs(d["std_difference"]))


def loop_payload(loop: BurnoutLoop, period: Optional[str] = None) -> Dict[str, Any]:
    res = loop.run(period)
    emp, comp = res.employees, res.company
    cur = loop.records[loop.records["period"] == res.period]
    scored = emp[emp["cbi_work_score"].notna()]

    by_dept = scored.groupby("department").agg(n=("forecast", "size"), now=("cbi_work_score", "mean"),
                                               forecast=("forecast", "mean"))
    by_dept = by_dept[by_dept["n"] >= 5]
    by_dept["change"] = by_dept["forecast"] - by_dept["now"]
    worst = by_dept["change"].idxmax() if not by_dept.empty else None
    company_change = float(scored["forecast"].mean() - scored["cbi_work_score"].mean()) if len(scored) else 0.0
    drv = drivers(cur, emp)
    m = res.forecast_metrics

    brief = {
        "worsening": {
            "value": f"{worst}" if worst is not None and by_dept.loc[worst, "change"] > 0 else "No department projected to rise",
            "detail": (f"Largest projected change next month: {_fmt(by_dept.loc[worst, 'change'])} CBI points "
                       f"({by_dept.loc[worst, 'now']:.1f} -> {by_dept.loc[worst, 'forecast']:.1f}, n={int(by_dept.loc[worst, 'n'])})."
                       if worst is not None else "Not enough scored employees per department."),
        },
        "how_much": {
            "value": f"{_fmt(company_change)} CBI pts (company)",
            "detail": (f"Department range {_fmt(by_dept['change'].min())} to {_fmt(by_dept['change'].max())} points; "
                       f"individual forecasts carry a 95% range of ±{m['interval_95_halfwidth']:.1f}.") if not by_dept.empty else "",
        },
        "why": {
            "value": " · ".join(f"{d['label']} {_fmt(d['difference'])}{d['unit']}" for d in drv[:2]) or "Not enough work data",
            "detail": "Flagged vs other employees this month (largest standardised differences). Association, not cause.",
            "drivers": drv,
        },
        "evidence": {
            "value": f"MAE {m['model']['mae']:.2f} vs {m['persistence']['mae']:.2f} (same-as-last-month)",
            "detail": (f"Employee-level split: {m['train_employees']} train / {m['test_employees']} test employees. "
                       f"95% range ±{m['interval_95_halfwidth']:.1f} covered {100 * m['interval_95_coverage']:.1f}% of held-out cases. "
                       "Synthetic panel; decision support, not diagnosis."),
        },
    }

    def example(mask: pd.Series, sort: str, ascending: bool = False) -> Optional[dict]:
        rows = emp[mask].sort_values(sort, ascending=ascending)
        if rows.empty:
            return None
        r = rows.iloc[0]
        return {"employee_id": r["employee_id"], "department": r["department"],
                "score": None if pd.isna(r["cbi_work_score"]) else round(float(r["cbi_work_score"]), 1),
                "hours": None if pd.isna(r["work_hours_per_week"]) else round(float(r["work_hours_per_week"]), 1)}

    iv = res.interventions
    done = iv[(iv["completion_status"] == "completed") & iv["follow_up_score"].notna()
              & (iv["follow_up_score_period"] <= res.period)]
    best = done.sort_values("observed_change").head(1)
    very_high = emp["level"] == "very_high"
    due = emp["status"].isin(["follow_up_due", "follow_up_overdue"])
    triage = {
        "very_high": {"count": int(very_high.sum()), "example": example(very_high, "cbi_work_score")},
        "follow_up_due": {"count": int(due.sum()), "overdue": int((emp["status"] == "follow_up_overdue").sum()),
                          "example": example(due, "employee_id", ascending=True)},
        "observed_improvement": {
            "count": int((emp["status"] == "outcome_improved").sum()),
            "example": None if best.empty else {
                "employee_id": best["employee_id"].iat[0], "intervention_type": best["intervention_type"].iat[0],
                "baseline": round(float(best["baseline_score"].iat[0]), 1),
                "follow_up": round(float(best["follow_up_score"].iat[0]), 1),
                "change": round(float(best["observed_change"].iat[0]), 1)},
        },
    }

    ivc = comp["interventions"]
    completed_followed = done[done["follow_up_score_period"] <= res.period]
    eff = res.effects
    impact = {
        "delivery": {"completed": ivc["completed"], "logged": ivc["logged"]},
        "follow_up": {"followed_up": ivc["followed_up"], "due": ivc["follow_up_due_by_now"]},
        "outcomes": {k: ivc[k] for k in ("improved", "no_change", "worsened")},
        "mean_change_completed": round(float(completed_followed["observed_change"].mean()), 1) if len(completed_followed) else None,
        "mean_comparison_change": round(float(eff["mean_comparison_change"].mean()), 1) if not eff.empty else None,
    }

    def records(df: pd.DataFrame) -> list:
        return df.replace({np.nan: None}).to_dict("records")

    return {
        "available": True, "period": res.period, "stages": STAGES, "company": comp,
        "brief": brief, "triage": triage, "impact": impact,
        "divisions": records(res.divisions), "effects": records(eff), "randomised_pilot": res.randomised,
        "calibration": records(res.calibration), "forecast_metrics": m,
        "notice": "Synthetic demonstration panel calibrated to real CBI norms. Observed changes are not causal effects.",
    }


def forecast_payload(loop: BurnoutLoop, cohort: Optional[str] = None) -> Dict[str, Any]:
    """Held-out monthly forecast points and a real next-month projection for the latest month."""
    rec = loop.records
    departments = sorted(rec["department"].dropna().unique().tolist())
    active = "All Workforce"
    if cohort and cohort.strip().lower() not in ("all", "all workforce", ""):
        hit = [d for d in departments if d.lower() == cohort.strip().lower()]
        if hit:
            active = hit[0]
            rec = rec[rec["department"] == active]

    model = loop.model
    pairs = transition_pairs(rec)
    test = pairs[pairs["employee_id"].isin(model.test_employees)].copy()
    test["pred"] = model.predict_mean(test) if len(test) else []
    points = [{"period": p, "actual_observed_t": round(g["cbi_work_score"].mean(), 2),
               "forecast_predicted_t1": round(g["pred"].mean(), 2),
               "persistence_baseline_t1": round(g["cbi_work_score"].mean(), 2),
               "future_actual_target_t1": round(g["target_next"].mean(), 2), "test_observations": int(len(g))}
              for p, g in test.groupby("period", sort=True)]

    latest = sorted(rec["period"].unique())[-1]
    last = rec[(rec["period"] == latest) & rec["cbi_work_score"].notna()]
    projected = float(model.predict_mean(last).mean()) if len(last) else float("nan")
    observed = float(last["cbi_work_score"].mean()) if len(last) else float("nan")
    se, margin = model.residual_sd, model.interval_95
    nxt = str(pd.Period(latest, freq="M") + 1)
    m = model.metrics

    iv = loop.linked
    waves = []
    if not iv.empty:
        counts = iv[iv["completion_status"] != "not_applicable"].groupby("referral_period").size()
        if len(counts):
            waves.append({"period": counts.idxmax(), "label": "Most referrals", "count": int(counts.max()),
                          "description": f"{int(counts.max())} support actions referred in this month."})
        pilot = iv[iv.get("trial_arm", pd.Series(dtype=str)).isin(["treatment", "control"])] if "trial_arm" in iv else pd.DataFrame()
        if len(pilot):
            p = pilot["referral_period"].mode().iat[0]
            arms = pilot["trial_arm"].value_counts()
            waves.append({"period": p, "label": "Randomised pilot", "count": int(len(pilot)),
                          "description": f"{int(arms.get('treatment', 0))} treatment vs {int(arms.get('control', 0))} waitlist control."})

    change = projected - observed
    rel = 100 * (m["persistence"]["mae"] - m["model"]["mae"]) / m["persistence"]["mae"]
    return {
        "available": True, "scale": "CBI Work-Related Subscale (0–100)", "active_cohort": active,
        "available_cohorts": ["All Workforce"] + departments, "monthly_points": points,
        "next_projection": {
            "forecast_period": nxt, "horizon": "1 Month Ahead (t+1)", "last_observed_period": latest,
            "last_observed_date": str(loop.records.loc[loop.records["period"] == latest, "assessment_date"].max())
            if "assessment_date" in loop.records else latest,
            "last_observed_mean_cbi": round(observed, 2), "projected_mean_cbi": round(projected, 2),
            "uncertainty_rmse": round(se, 2), "uncertainty_lower_cbi": round(max(0.0, projected - se), 2),
            "uncertainty_upper_cbi": round(min(100.0, projected + se), 2), "standard_error_se": round(se, 2),
            "empirical_95_margin": round(margin, 2), "interval_95_lower": round(max(0.0, projected - margin), 2),
            "interval_95_upper": round(min(100.0, projected + margin), 2),
            "interval_explanation": (f"Held-out residual SD = {se:.2f} CBI points; 95% range = ±{margin:.2f} for an "
                                     f"individual forecast, covering {100 * m['interval_95_coverage']:.1f}% of held-out cases."),
        },
        "benchmarks": {"persistence_baseline": m["persistence"], "ridge": m["model"]},
        "intervention_waves": waves,
        "forecast_insight": {
            "direction": f"Projected mean change {change:+.1f} CBI points ({observed:.1f} -> {projected:.1f}) for {nxt}",
            "primary_evidence": "See 'Why' drivers: computed from flagged vs other employees this month.",
            "benchmark_comparison": (f"Forecast MAE {m['model']['mae']:.2f} vs same-as-last-month {m['persistence']['mae']:.2f} "
                                     f"({rel:.1f}% lower error) on held-out employees."),
            "material_limitations": "Assumes current conditions continue; unmeasured personal and project demands move "
                                    "individual scores. Not a clinical prognosis.",
        },
        "leakage_safeguard": (f"Employee-level split: {m['train_employees']} training vs {m['test_employees']} test employees, "
                              f"{m['test_pairs']} held-out month pairs; no employee appears in both."),
        "synthetic_notice": "Synthetic demonstration panel (burnoutiq_synthetic_v1).",
    }
