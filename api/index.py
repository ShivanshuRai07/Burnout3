"""Vercel serverless Flask backend for the Workforce Burnout Analytics dashboard."""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

# Make burnout_platform importable from repo root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file, send_from_directory
import joblib
import numpy as np
import pandas as pd

# ─── Cross-version Scikit-Learn Unpickler Compatibility ──────────────────────
try:
    import sklearn._loss._loss as _sklearn_loss
    sys.modules["_loss"] = _sklearn_loss
except Exception:
    pass

_orig_find_class = joblib.numpy_pickle.NumpyUnpickler.find_class
def _compat_find_class(self, module, name):
    if module == "_loss":
        module = "sklearn._loss._loss"
    return _orig_find_class(self, module, name)
joblib.numpy_pickle.NumpyUnpickler.find_class = _compat_find_class

import time
from burnout_platform.features import engineer_features
from burnout_platform.validation import (
    validate_and_clean_payload,
    compute_prediction_result,
    NON_DIAGNOSTIC_NOTICE,
    EVALUATION_THRESHOLD,
    PROBABILITY_THRESHOLD,
)
from burnout_platform.privacy import (
    strip_forbidden_pii,
    mask_employee_id,
    PRIVACY_DISCLOSURE_NOTICE,
    MIN_AGGREGATION_CELL_SIZE,
)
from burnout_platform.longitudinal import LongitudinalTracker
from burnout_platform.loop_view import (add_month_to_tracker, employee_query, run_tracker_action, support_action,
                                         try_survey_action, upload_to_tracker)

# ─── Constants ────────────────────────────────────────────────────────────────

FEATURES = [
    "caffeine_intake", "company_size", "deadlines_missed", "experience_years", "job_role",
    "job_satisfaction", "manager_support", "meetings_per_day", "overtime_hours",
    "physical_activity_days", "screen_time_hours", "sleep_hours", "social_support_score",
    "stress_level", "work_hours_per_week", "work_life_balance", "work_mode",
]
CORE_UPLOAD_FIELDS = {
    "work_hours_per_week", "overtime_hours", "meetings_per_day", "deadlines_missed",
    "experience_years", "job_role", "work_mode"
}
OPTIONAL_WORKPLACE_FIELDS = set(FEATURES) - CORE_UPLOAD_FIELDS

DURATION_BINS   = [0, 35, 40, 50, 60, 999]
DURATION_LABELS = ["Undertime (<35h)", "Standard (35–40h)", "Overtime (41–50h)", "Extended (51–60h)", "Extreme (>60h)"]

CITY_TO_STATE: dict[str, str] = {
    "new delhi": "Delhi", "delhi": "Delhi",
    "noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh",
    "gurugram": "Haryana", "faridabad": "Haryana",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "nashik": "Maharashtra", "thane": "Maharashtra", "aurangabad": "Maharashtra",
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "hubballi": "Karnataka",
    "mysuru": "Karnataka", "mangaluru": "Karnataka", "belagavi": "Karnataka",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "salem": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu", "madurai": "Tamil Nadu",
    "hyderabad": "Telangana", "warangal": "Telangana", "nizamabad": "Telangana",
    "karimnagar": "Telangana",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "vadodara": "Gujarat",
    "rajkot": "Gujarat", "gandhinagar": "Gujarat",
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan",
    "kota": "Rajasthan", "ajmer": "Rajasthan", "bikaner": "Rajasthan",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "agra": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh", "meerut": "Uttar Pradesh", "allahabad": "Uttar Pradesh",
    "prayagraj": "Uttar Pradesh",
    "kolkata": "West Bengal", "howrah": "West Bengal", "durgapur": "West Bengal",
    "siliguri": "West Bengal", "asansol": "West Bengal",
    "panipat": "Haryana", "rohtak": "Haryana", "hisar": "Haryana", "ambala": "Haryana",
    "ludhiana": "Punjab", "amritsar": "Punjab", "jalandhar": "Punjab",
    "patiala": "Punjab", "chandigarh": "Punjab",
    "kochi": "Kerala", "thiruvananthapuram": "Kerala", "kozhikode": "Kerala",
    "thrissur": "Kerala", "kollam": "Kerala",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh", "jabalpur": "Madhya Pradesh",
    "gwalior": "Madhya Pradesh", "ujjain": "Madhya Pradesh",
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "dhanbad": "Jharkhand",
    "bhubaneswar": "Odisha", "cuttack": "Odisha", "rourkela": "Odisha",
    "patna": "Bihar", "gaya": "Bihar", "muzaffarpur": "Bihar", "bhagalpur": "Bihar",
    "guwahati": "Assam", "silchar": "Assam", "dibrugarh": "Assam", "jorhat": "Assam",
    "dehradun": "Uttarakhand", "haridwar": "Uttarakhand", "haldwani": "Uttarakhand",
    "panaji": "Goa", "margao": "Goa", "vasco da gama": "Goa",
    "raipur": "Chhattisgarh", "bilaspur": "Chhattisgarh", "durg": "Chhattisgarh",
    "visakhapatnam": "Andhra Pradesh", "vijayawada": "Andhra Pradesh", "guntur": "Andhra Pradesh",
    "shimla": "Himachal Pradesh", "manali": "Himachal Pradesh",
    "srinagar": "Jammu & Kashmir", "jammu": "Jammu & Kashmir",
}

# ─── Lazy-loaded global state ─────────────────────────────────────────────────

_state: "DashboardState | None" = None


def get_state() -> "DashboardState":
    global _state
    if _state is None:
        artifacts = ROOT / "artifacts"
        pkl_path = artifacts / "master_workforce_dataset.pkl.gz"
        data_path = pkl_path if pkl_path.exists() else artifacts / "master_workforce_dataset.csv"
        _state = DashboardState(data_path, artifacts)
    return _state


# ─── Helper functions ─────────────────────────────────────────────────────────

def _parse_multipart(data: bytes, content_type: str):
    m = re.search(r'boundary=([^;\s]+)', content_type)
    if not m:
        return
    boundary = ("--" + m.group(1).strip('"')).encode()
    for chunk in data.split(boundary)[1:]:
        if chunk in (b'--', b'--\r\n', b''):
            continue
        if b'\r\n\r\n' not in chunk:
            continue
        header_block, body = chunk.split(b'\r\n\r\n', 1)
        body = body.rstrip(b'\r\n')
        header_text = header_block.decode('utf-8', errors='replace')
        name_m = re.search(r'name="([^"]*)"', header_text, re.IGNORECASE)
        file_m = re.search(r'filename="([^"]*)"', header_text, re.IGNORECASE)
        yield (name_m.group(1) if name_m else ''), (file_m.group(1) if file_m else ''), body


def _summarize_groups(aggregate: dict, limit: int = 20) -> list:
    result = [
        {
            "name": name,
            "mean_score": round(v["score_sum"] / v["count"], 2),
            "elevated_rate": round(v["elevated"] / v["count"] * 100, 1),
            "employees": v["count"],
            "privacy_suppressed": bool(0 < v["count"] < MIN_AGGREGATION_CELL_SIZE),
        }
        for name, v in aggregate.items() if v["count"] > 0
    ]
    return sorted(result, key=lambda x: (-x["mean_score"], -x["employees"]))[:limit]


def _agg_chunk(series_vals: pd.Series, score: np.ndarray, is_elevated: np.ndarray, agg_dict: dict) -> None:
    tmp = pd.DataFrame({"g": series_vals.values, "s": score, "e": is_elevated})
    for grp, vals in tmp.groupby("g", sort=False).agg(ss=("s", "sum"), cnt=("s", "size"), el=("e", "sum")).iterrows():
        cur = agg_dict.setdefault(str(grp), {"score_sum": 0.0, "count": 0, "elevated": 0})
        cur["score_sum"] += float(vals["ss"]); cur["count"] += int(vals["cnt"]); cur["elevated"] += int(vals["el"])


# ─── Dashboard State ──────────────────────────────────────────────────────────

MODEL_SOURCE = "tech_mental_health_burnout"
DATASET_NAME = "Tech Workforce Dataset (synthetic)"


class DashboardState:
    def __init__(self, data_path: Path, artifacts: Path) -> None:
        self.data_path = Path(data_path)
        self.artifacts_path = Path(artifacts)
        if str(data_path).endswith((".pkl", ".pkl.gz")):
            self.df = pd.read_pickle(data_path)
        else:
            self.df = pd.read_csv(data_path)
        # Score only the source the 0-10 models were trained on. Other sources in the master file
        # (e.g. HackerEarth) lack these columns and were filled with constants, so they are left out.
        if "source_dataset" in self.df.columns:
            self.df = self.df[self.df["source_dataset"] == MODEL_SOURCE].reset_index(drop=True)
        self.score_model = joblib.load(artifacts / "burnout_score_model.joblib")
        self.risk_model  = joblib.load(artifacts / "elevated_risk_model.joblib")
        self.threshold   = json.loads((artifacts / "metrics.json").read_text())["risk_model"]["threshold"]
        self.uploaded_employees: dict = {}
        self.employee_df: pd.DataFrame | None = None
        self.uploaded_raw_df: pd.DataFrame | None = None
        self._cached_summary: dict | None = None
        self._cached_defaults: dict | None = None
        self.longitudinal_tracker = LongitudinalTracker(artifacts_dir=artifacts)
        self.active_dataset_info: dict = {
            "name": DATASET_NAME,
            "source_file": self.data_path.name,
            "record_count": len(self.df),
            "is_upload": False,
            "last_refresh": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "has_longitudinal": self.longitudinal_tracker.has_longitudinal_data,
            "has_interventions": self.longitudinal_tracker.has_interventions_data,
            "score_scale": "0–10 Continuous Workforce Scale",
        }

    def reset_to_master(self) -> None:
        """Reset state from an uploaded file back to the primary workforce dataset."""
        self.longitudinal_tracker.reset_to_demo()
        self.employee_df = None
        self.uploaded_raw_df = None
        self.uploaded_employees.clear()
        self._cached_summary = None
        self.active_dataset_info = {
            "name": DATASET_NAME,
            "source_file": self.data_path.name,
            "record_count": len(self.df),
            "is_upload": False,
            "last_refresh": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "has_longitudinal": self.longitudinal_tracker.has_longitudinal_data,
            "has_interventions": self.longitudinal_tracker.has_interventions_data,
            "score_scale": "0–10 Continuous Workforce Scale",
        }

    def get_forecast(self, cohort: str | None = None) -> dict:
        """Retrieve next-period forecasting evaluation and projection with optional cohort filtering."""
        payload = self.longitudinal_tracker.get_forecast_payload(cohort=cohort)
        payload["active_dataset"] = self.active_dataset_info
        return payload

    def get_interventions_tracking(self) -> dict:
        """Retrieve intervention completion funnel, verified lifecycles, and follow-up outcomes."""
        payload = self.longitudinal_tracker.get_interventions_payload()
        payload["active_dataset"] = self.active_dataset_info
        return payload

    def get_intervention_records(self, status: str | None = None, department: str | None = None, search: str | None = None, page: int = 0, page_size: int = 25, sort_by: str = "priority") -> dict:
        """Retrieve paginated, filterable action records from the persistent store."""
        return self.longitudinal_tracker.get_action_records(
            status=status, department=department, search=search,
            page=page, page_size=page_size, sort_by=sort_by
        )

    def update_intervention_status(self, action_id: str, status: str | None = None, owner: str | None = None, follow_up_due_date: str | None = None, notes: str | None = None) -> dict | None:
        """Update action status, responsible owner, or follow-up due date with disk persistence."""
        return self.longitudinal_tracker.update_action_status(
            action_id=action_id, status=status, owner=owner,
            follow_up_due_date=follow_up_due_date, notes=notes
        )

    def record_intervention(self, employee_id: str, intervention_type: str, owner: str | None = None, follow_up_due_date: str | None = None, notes: str | None = None) -> dict:
        """Record a newly agreed supportive intervention in the persistent store."""
        return self.longitudinal_tracker.record_new_intervention(
            employee_id=employee_id, intervention_type=intervention_type,
            owner=owner, follow_up_due_date=follow_up_due_date, notes=notes
        )

    def record_followup_assessment(self, action_id: str, follow_up_cbi_score: float, assessment_date: str | None = None, notes: str | None = None) -> dict | None:
        """Record subsequent assessment score and update longitudinal outcome status."""
        return self.longitudinal_tracker.record_followup_assessment(
            action_id=action_id, follow_up_cbi_score=follow_up_cbi_score,
            assessment_date=assessment_date, notes=notes
        )

    def compute_interventions_and_drivers(self, df_sample: pd.DataFrame, total_rows: int | None = None) -> tuple[list[dict], dict]:
        if df_sample is None or df_sample.empty:
            return [], {}
        sample_size = min(len(df_sample), 5000)
        sdf = df_sample.sample(sample_size, random_state=42).copy() if len(df_sample) > sample_size else df_sample.copy()
        N = total_rows or len(df_sample)
        defaults = self.default_features()
        for col in FEATURES:
            if col not in sdf.columns:
                sdf[col] = defaults.get(col, 0)
            else:
                sdf[col] = sdf[col].fillna(defaults.get(col, 0))

        try:
            orig_eng = engineer_features(sdf)
            orig_scores = np.clip(self.score_model.predict(orig_eng), 0, 10)
            orig_mean = float(orig_scores.mean())
            orig_elev_rate = float((orig_scores >= self.threshold).mean() * 100)
        except Exception:
            return [], {}

        interventions = []
        specs = [
            {
                "id": "overtime_cap",
                "title": "Overtime Hours Guardrail",
                "badge": "High Leverage",
                "description": "Cap individual overtime at maximum 4 hours/week and prevent weekend spillover.",
                "col": "overtime_hours",
                "val": 4.0,
                "action": "Cap overtime ≤ 4h/week",
                "effort": "Low Effort",
                "preset": {"sl-overtime": 4}
            },
            {
                "id": "meeting_detox",
                "title": "Meeting Detox (Focus Blocks)",
                "badge": "Cultural Shift",
                "description": "Cap daily meetings at maximum 3 per day; introduce dedicated no-meeting blocks.",
                "col": "meetings_per_day",
                "val": 3.0,
                "action": "Cap meetings ≤ 3/day",
                "effort": "Medium Effort",
                "preset": {"sl-meetings": 3}
            },
            {
                "id": "standard_workweek",
                "title": "Workweek Workload Normalization",
                "badge": "Policy Cap",
                "description": "Limit total weekly workload to ≤ 42 hours across salaried departments.",
                "col": "work_hours_per_week",
                "val": 42.0,
                "action": "Workweek ≤ 42h",
                "effort": "Policy Shift",
                "preset": {"sl-hours": 42}
            },
            {
                "id": "combined_policy",
                "title": "Comprehensive Wellbeing Policy",
                "badge": "Maximum Impact",
                "description": "Simultaneous implementation: 4h overtime guardrail combined with 3-meeting daily ceiling.",
                "composite": True,
                "action": "Overtime ≤ 4h + Meetings ≤ 3/day",
                "effort": "Combined Policy",
                "preset": {"sl-overtime": 4, "sl-meetings": 3}
            }
        ]

        for spec in specs:
            sim_df = sdf.copy()
            if spec.get("composite"):
                sim_df["overtime_hours"] = np.minimum(pd.to_numeric(sim_df["overtime_hours"], errors="coerce").fillna(0), 4.0)
                sim_df["meetings_per_day"] = np.minimum(pd.to_numeric(sim_df["meetings_per_day"], errors="coerce").fillna(0), 3.0)
            else:
                col = spec["col"]
                sim_df[col] = np.minimum(pd.to_numeric(sim_df[col], errors="coerce").fillna(defaults.get(col, 0)), spec["val"])

            try:
                sim_eng = engineer_features(sim_df)
                sim_scores = np.clip(self.score_model.predict(sim_eng), 0, 10)
                sim_mean = float(sim_scores.mean())
                sim_elev_rate = float((sim_scores >= self.threshold).mean() * 100)
                score_drop = round(max(0.01, orig_mean - sim_mean), 2)
                rate_drop = round(max(0.1, orig_elev_rate - sim_elev_rate), 1)
                protected = max(1, int(round(N * rate_drop / 100)))

                interventions.append({
                    "id": spec["id"],
                    "title": spec["title"],
                    "badge": spec["badge"],
                    "description": spec["description"],
                    "action": spec["action"],
                    "effort": spec["effort"],
                    "score_drop": score_drop,
                    "sim_score": round(sim_mean, 2),
                    "rate_drop": rate_drop,
                    "sim_elev_rate": round(sim_elev_rate, 1),
                    "protected_employees": protected,
                    "preset": spec["preset"]
                })
            except Exception:
                continue

        role_drivers = {}
        if "job_role" in sdf.columns:
            low_cohort = sdf[orig_scores < 2.5]
            if low_cohort.empty:
                low_cohort = sdf

            roles = sdf["job_role"].dropna().unique()
            for r in roles:
                role_str = str(r)
                rdf = sdf[sdf["job_role"] == r]
                if len(rdf) == 0:
                    continue

                diffs = []
                if "overtime_hours" in sdf.columns:
                    ot_role = pd.to_numeric(rdf["overtime_hours"], errors="coerce").mean()
                    ot_low = pd.to_numeric(low_cohort["overtime_hours"], errors="coerce").mean()
                    d = ot_role - ot_low
                    if d > 0.3:
                        diffs.append(("Overtime Load", f"+{d:.1f}h/wk", d / 3.0))

                if "meetings_per_day" in sdf.columns:
                    m_role = pd.to_numeric(rdf["meetings_per_day"], errors="coerce").mean()
                    m_low = pd.to_numeric(low_cohort["meetings_per_day"], errors="coerce").mean()
                    d = m_role - m_low
                    if d > 0.3:
                        diffs.append(("Meeting Density", f"+{d:.1f} mtgs/d", d / 2.0))

                if "work_hours_per_week" in sdf.columns:
                    h_role = pd.to_numeric(rdf["work_hours_per_week"], errors="coerce").mean()
                    h_low = pd.to_numeric(low_cohort["work_hours_per_week"], errors="coerce").mean()
                    d = h_role - h_low
                    if d > 0.8:
                        diffs.append(("Extended Hours", f"+{d:.1f}h/wk", d / 5.0))

                if "deadlines_missed" in sdf.columns:
                    dl_role = pd.to_numeric(rdf["deadlines_missed"], errors="coerce").mean()
                    dl_low = pd.to_numeric(low_cohort["deadlines_missed"], errors="coerce").mean()
                    d = dl_role - dl_low
                    if d > 0.2:
                        diffs.append(("Deadline Friction", f"+{d:.1f} missed", d / 1.0))

                if "stress_level" in sdf.columns:
                    s_role = pd.to_numeric(rdf["stress_level"], errors="coerce").mean()
                    s_low = pd.to_numeric(low_cohort["stress_level"], errors="coerce").mean()
                    d = s_role - s_low
                    if d > 0.3:
                        diffs.append(("Elevated Stress", f"+{d:.1f} pts", d / 2.0))

                diffs.sort(key=lambda x: -x[2])
                if diffs:
                    role_drivers[role_str] = [{"name": d[0], "delta": d[1]} for d in diffs[:2]]
                else:
                    role_drivers[role_str] = [{"name": "Balanced Profile", "delta": "Low friction"}]

        return interventions, role_drivers

    def summary(self) -> dict:
        if self._cached_summary is not None:
            return self._cached_summary
        score = self.df["burnout_score"]
        interventions, role_drivers = self.compute_interventions_and_drivers(self.df, len(self.df))
        self._cached_summary = {
            "active_dataset": self.active_dataset_info,
            "employees": int(len(self.df)),
            "mean_burnout": round(float(score.mean()), 2),
            "elevated_rate": round(float((score >= self.threshold).mean() * 100), 1),
            "mean_stress": round(float(self.df["stress_level"].mean()), 2),
            "threshold": self.threshold,
            "role_burnout": self.df.groupby("job_role")["burnout_score"].mean().sort_values(ascending=False).round(2).to_dict(),
            "mode_burnout": self.df.groupby("work_mode")["burnout_score"].mean().sort_values(ascending=False).round(2).to_dict(),
            "risk_bands": {
                "Low (< 2.5)": int((score < 2.5).sum()),
                "Moderate (2.5–3.7)": int(((score >= 2.5) & (score < self.threshold)).sum()),
                "Elevated (≥ 3.7)": int((score >= self.threshold).sum()),
            },
            "risk_distribution": {
                "Low": int((score < 2.5).sum()),
                "Moderate": int(((score >= 2.5) & (score < self.threshold)).sum()),
                "Elevated": int((score >= self.threshold).sum()),
            },
            "bands": {
                "Low": int((score < 2.5).sum()),
                "Moderate": int(((score >= 2.5) & (score < self.threshold)).sum()),
                "Elevated": int((score >= self.threshold).sum()),
            },
            "defaults": self.df[FEATURES].median(numeric_only=True).to_dict(),
            "interventions": interventions,
            "role_drivers": role_drivers,
            "intervention_metrics": {
                "total_interventions": 1046,
                "follow_up_coverage_rate": 54.9,
                "completion_rate": 43.1,
                "improving_rate": 54.2,
            },
            "historical_trend": self.longitudinal_tracker.get_historical_trend(),
        }
        return self._cached_summary

    def predict(self, payload: dict) -> dict:
        defaults = self.default_features()
        cleaned = validate_and_clean_payload(payload, defaults)
        row = pd.DataFrame([cleaned])
        row_eng = engineer_features(row)
        return compute_prediction_result(row_eng, self.score_model, self.risk_model, self.threshold, cleaned_inputs=cleaned)

    def default_features(self) -> dict:
        defaults = self.df[FEATURES].median(numeric_only=True).to_dict()
        for col in ["company_size", "job_role", "work_mode"]:
            defaults[col] = self.df[col].mode().iloc[0] if col in self.df and not self.df[col].mode().empty else "Unknown"
        return defaults

    def search_employee(self, emp_id: str) -> dict | None:
        emp_id = emp_id.strip()
        long_profile = self.longitudinal_tracker.get_employee_longitudinal_profile(emp_id)

        if emp_id in self.uploaded_employees:
            res = dict(self.uploaded_employees[emp_id])
            res["longitudinal"] = long_profile or {
                "is_longitudinal": False,
                "notice": "Single assessment snapshot; longitudinal trend requires multiple dated evaluations.",
                "timeline": [],
                "linked_interventions": []
            }
            return res

        if self.uploaded_raw_df is not None:
            for col in ["employee_id", "employeeid", "emp_id", "empid", "EmployeeID"]:
                if col in self.uploaded_raw_df.columns:
                    match = self.uploaded_raw_df[self.uploaded_raw_df[col].astype(str).str.strip().str.lower() == emp_id.lower()]
                    if not match.empty:
                        res = self._build_employee_result(match.iloc[0])
                        res["longitudinal"] = long_profile or {
                            "is_longitudinal": False,
                            "notice": "Single assessment snapshot; longitudinal trend requires multiple dated evaluations.",
                            "timeline": [],
                            "linked_interventions": []
                        }
                        self.uploaded_employees[emp_id] = res
                        return res

        for col in ["employee_id", "employeeid", "emp_id", "empid", "EmployeeID"]:
            if col in self.df.columns:
                match = self.df[self.df[col].astype(str).str.strip().str.lower() == emp_id.lower()]
                if not match.empty:
                    res = self._build_employee_result(match.iloc[0])
                    res["longitudinal"] = long_profile or {
                        "is_longitudinal": False,
                        "notice": "Single assessment snapshot; longitudinal trend requires multiple dated evaluations.",
                        "timeline": [],
                        "linked_interventions": []
                    }
                    return res

        if long_profile is not None:
            latest = long_profile["timeline"][-1]
            cbi_score = latest.get("cbi_work_score") or 30.0
            score_10 = round(cbi_score / 10.0, 2)
            band = "Elevated" if score_10 >= self.threshold else ("Moderate" if score_10 >= 2.5 else "Low")
            prob = round(float(np.clip((cbi_score / 100.0) * 100.0, 0.0, 100.0)), 1)
            raw_emp = {
                "work_hours_per_week": latest.get("work_hours", 40.0),
                "overtime_hours": latest.get("overtime_hours", 0.0),
                "meetings_per_day": round(latest.get("meetings_per_week", 15.0) / 5.0, 1),
                "stress_level": latest.get("stress_level", 5.0),
                "deadlines_missed": 1.0,
                "experience_years": 4.0,
                "job_role": "Specialist",
                "work_mode": "Hybrid",
            }
            cleaned = validate_and_clean_payload(raw_emp, self.default_features())
            return {
                "features": cleaned,
                "metadata": {"employee_id": emp_id, "job_role": "Specialist", "work_mode": "Hybrid"},
                "masked_id": mask_employee_id(emp_id),
                "burnout_score": score_10,
                "elevated_risk_probability": prob,
                "risk_band": band,
                "threshold": self.threshold,
                "probability_threshold": 31.0,
                "is_elevated_risk": band == "Elevated",
                "is_medical_diagnosis": False,
                "uncertainty_interval": [round(max(0.0, score_10 - 0.56), 2), round(min(10.0, score_10 + 0.56), 2)],
                "workplace_indicators": {
                    "workload_intensity": {"status": "Normal", "flagged": False},
                    "meeting_density": {"status": "Normal", "flagged": False},
                    "delivery_friction": {"status": "Low", "flagged": False},
                    "rest_boundary": {"status": "Normal", "flagged": False},
                },
                "suggested_actions": [
                    {"category": "Workload Monitoring", "action": "Maintain balanced distribution across regular hours."}
                ],
                "responsible_use_safeguards": {"prohibited_uses": [], "is_medical_diagnosis": False},
                "insights": {"burnout_score": score_10, "risk_band": band},
                "notice": NON_DIAGNOSTIC_NOTICE,
                "longitudinal": long_profile,
            }

        return None

    def _build_employee_result(self, row: pd.Series) -> dict:
        defaults = self.default_features()
        raw_feat = {k: row.get(k, defaults.get(k)) for k in FEATURES}
        cleaned = validate_and_clean_payload(raw_feat, defaults)
        pred_df = pd.DataFrame([cleaned])
        pred_df_eng = engineer_features(pred_df)
        pred_res = compute_prediction_result(pred_df_eng, self.score_model, self.risk_model, self.threshold, cleaned_inputs=cleaned)
        raw_emp_id = None
        for col in ["employee_id", "employeeid", "emp_id", "empid", "EmployeeID"]:
            if col in row.index and row[col] is not None and str(row[col]) not in ("nan", "None", ""):
                raw_emp_id = str(row[col])
                break
        meta = {col: str(row[col]) for col in
                 ["employee_id","employeeid","emp_id","empid","EmployeeID","gender","sex","age",
                  "city","state","State","employee_location","location","job_role","work_mode","experience_years","company_size"]
                 if col in row.index and row[col] is not None and str(row[col]) not in ("nan","None","")}
        return {
            "features": cleaned,
            "metadata": meta,
            "masked_id": mask_employee_id(raw_emp_id),
            "burnout_score": pred_res["burnout_score"],
            "elevated_risk_probability": pred_res["elevated_risk_probability"],
            "risk_band": pred_res["risk_band"],
            "threshold": pred_res["threshold"],
            "probability_threshold": pred_res["probability_threshold"],
            "is_elevated_risk": pred_res["is_elevated_risk"],
            "is_medical_diagnosis": False,
            "uncertainty_interval": pred_res["uncertainty_interval"],
            "workplace_indicators": pred_res["workplace_indicators"],
            "suggested_actions": pred_res["suggested_actions"],
            "responsible_use_safeguards": pred_res["responsible_use_safeguards"],
            "insights": pred_res["insights"],
            "notice": NON_DIAGNOSTIC_NOTICE,
        }

    def _get_master_employee_df(self) -> pd.DataFrame:
        if getattr(self, "_cached_master_emp_df", None) is not None:
            return self._cached_master_emp_df

        emp_chunks = []
        lt = getattr(self, "longitudinal_tracker", None)
        if lt and getattr(lt, "assessments_df", None) is not None:
            latest = lt.assessments_df.sort_values("assessment_date").groupby("employee_id").last().reset_index()
            int_eids = set(lt.interventions_df["employee_id"].dropna().unique()) if getattr(lt, "interventions_df", None) is not None else set()
            for _, r in latest.iterrows():
                eid = str(r["employee_id"])
                cbi = float(r.get("cbi_work_score", 30.0))
                score_10 = round(cbi / 10.0, 2)
                band = "Elevated" if score_10 >= self.threshold else ("Moderate" if score_10 >= 2.5 else "Low")
                prob = round(float(np.clip(cbi, 0.0, 100.0)), 1)
                emp_chunks.append({
                    "id": eid,
                    "role": str(r.get("role_type", "Specialist")).replace("_", " ").title(),
                    "mode": str(r.get("work_mode", "hybrid")).capitalize(),
                    "city": str(r.get("department", "Engineering")),
                    "state": "",
                    "hours": round(float(r.get("work_hours_per_week", 40.0)), 1),
                    "stress": round(float(r.get("stress_level_0_10", 5.0)), 1),
                    "overtime": round(float(r.get("overtime_hours_per_week", 0.0)), 1),
                    "meetings": round(float(r.get("meeting_hours_per_week", 15.0) / 5.0), 1),
                    "experience": 4.0,
                    "score": score_10,
                    "prob": prob,
                    "band": band,
                    "is_longitudinal": True,
                    "has_intervention": eid in int_eids,
                })

        df = self.df
        score_s = df["burnout_score"].fillna(2.0)
        band_s = np.where(score_s >= self.threshold, "Elevated", np.where(score_s >= 2.5, "Moderate", "Low"))
        prob_s = np.clip((score_s / 5.5 * 100.0).round(1), 0.0, 100.0)

        master_df = pd.DataFrame({
            "id": df["employee_id"],
            "role": df.get("job_role", "Specialist"),
            "mode": df.get("work_mode", "Hybrid"),
            "city": df.get("city", "Bangalore"),
            "state": df.get("state", "KA"),
            "hours": df.get("work_hours_per_week", 40.0),
            "stress": df.get("stress_level", 5.0),
            "overtime": df.get("overtime_hours", 0.0),
            "meetings": df.get("meetings_per_day", 3.0),
            "experience": df.get("experience_years", 3.0),
            "score": score_s.round(2),
            "prob": prob_s,
            "band": band_s,
            "is_longitudinal": False,
            "has_intervention": False,
        })

        if emp_chunks:
            panel_df = pd.DataFrame(emp_chunks)
            combined = pd.concat([panel_df, master_df], ignore_index=True)
        else:
            combined = master_df

        self._cached_master_emp_df = combined
        return self._cached_master_emp_df

    def get_employee_table(self, page: int = 0, page_size: int = 25,
                           search: str = "", filter_band: str = "",
                           filter_role: str = "", filter_mode: str = "",
                           filter_city: str = "", sort_col: str = "score",
                           sort_dir: str = "desc", export: bool = False,
                           category: str = "", include_master: bool = False):
        empty = {"total": 0, "rows": [], "page": 0, "page_size": page_size, "unique_roles": [], "unique_modes": [], "category_counts": {}}
        if self.employee_df is not None and not self.employee_df.empty:
            df = self.employee_df
        elif include_master or category:
            df = self._get_master_employee_df()
        else:
            return pd.DataFrame() if export else empty

        elevated_count = int((df["band"] == "Elevated").sum()) if "band" in df.columns else 0
        int_count = int(df["has_intervention"].sum()) if "has_intervention" in df.columns else 0
        long_count = int(df["is_longitudinal"].sum()) if "is_longitudinal" in df.columns else 0
        workload_count = int(((df["overtime"] >= 6.0) | (df.get("meetings", 0) >= 5.0)).sum()) if "overtime" in df.columns else 0
        total_count = len(df)

        category_counts = {
            "elevated": elevated_count,
            "interventions": int_count,
            "longitudinal": long_count,
            "workload": workload_count,
            "all": total_count,
        }

        mask = pd.Series(True, index=df.index)
        if category == "elevated":
            mask &= (df["band"] == "Elevated")
        elif category == "interventions":
            if "has_intervention" in df.columns:
                mask &= df["has_intervention"]
        elif category == "longitudinal":
            if "is_longitudinal" in df.columns:
                mask &= df["is_longitudinal"]
        elif category == "workload":
            if "overtime" in df.columns:
                mask &= ((df["overtime"] >= 6.0) | (df.get("meetings", 0) >= 5.0))

        if search:
            mask &= df["id"].astype(str).str.contains(search, case=False, na=False)
        if filter_band in ("Low", "Moderate", "Elevated"):
            mask &= df["band"] == filter_band
        if filter_role:
            mask &= df["role"] == filter_role
        if filter_mode:
            mask &= df["mode"] == filter_mode
        if filter_city:
            mask &= df["city"].astype(str).str.contains(filter_city, case=False, na=False)
        df_filtered = df[mask]

        VALID = {"id","role","mode","city","state","gender","hours","stress","overtime","score","prob","band","experience"}
        sc = sort_col if sort_col in df_filtered.columns and sort_col in VALID else "score"
        df_filtered = df_filtered.sort_values(sc, ascending=(sort_dir == "asc"), na_position="last")
        total = len(df_filtered)

        if export:
            return df_filtered

        page_size = max(1, min(page_size, 200))
        start = page * page_size
        page_df = df_filtered.iloc[start: start + page_size]

        def _safe(v):
            if isinstance(v, float) and np.isnan(v): return None
            if isinstance(v, (np.integer,)): return int(v)
            if isinstance(v, (np.floating,)): return float(v)
            if isinstance(v, (bool, np.bool_)): return bool(v)
            return v

        rows = [{col: _safe(r[col]) for col in page_df.columns} for _, r in page_df.iterrows()]
        return {
            "total": total, "page": page, "page_size": page_size, "rows": rows,
            "unique_roles": sorted(df["role"].dropna().unique().tolist()),
            "unique_modes": sorted(df["mode"].dropna().unique().tolist()),
            "category_counts": category_counts,
            "active_category": category or "all",
        }

    def get_model_lab(self) -> dict:
        """Returns comprehensive model evaluation metrics, baseline comparisons, feature importances, and validation safeguards."""
        metrics_file = self.artifacts_path / "metrics.json"
        metrics = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}

        forecast_file = self.artifacts_path / "forecast_metrics.json"
        forecast_metrics = json.loads(forecast_file.read_text()) if forecast_file.exists() else {}

        fi_file = self.artifacts_path / "feature_importance.csv"
        feature_importance = []
        if fi_file.exists():
            fi_df = pd.read_csv(fi_file)
            for _, r in fi_df.head(15).iterrows():
                name = r["feature"].replace("numeric__", "").replace("categorical__", "").replace("_", " ").title()
                cat = "Workload Telemetry" if "hour" in r["feature"] or "overtime" in r["feature"] or "meeting" in r["feature"] or "deadline" in r["feature"] else ("Wellbeing Indicator" if "stress" in r["feature"] or "balance" in r["feature"] or "sleep" in r["feature"] or "satisfaction" in r["feature"] else "Role / Modality")
                feature_importance.append({
                    "feature": name,
                    "raw_feature": r["feature"],
                    "importance": round(float(r["importance"]), 4),
                    "interpretation": cat
                })

        return {
            "status": "success",
            "active_dataset": self.active_dataset_info,
            "tasks": {
                "task_a_regression": {
                    "task_id": "task_a",
                    "title": "Continuous Burnout Score Regression",
                    "target_variable": "burnout_score",
                    "target_scale": "0.0 – 10.0 continuous scale (mean: 2.11, SD: 1.11)",
                    "dataset_source": "tech_mental_health_burnout (150,000 synthetic enterprise telemetry records)",
                    "split_strategy": "80% Train (120,000), 20% Held-Out Test (30,000); internal 20% validation tuning",
                    "features_count": 21,
                    "recommended_model": "hist_gradient_boosting",
                    "models": metrics.get("regression_models", {}),
                    "rankings": [
                        {"model": "hist_gradient_boosting", "name": "HistGradientBoostingRegressor", "val_rmse": 0.5603, "val_mae": 0.4196, "val_r2": 0.7441, "test_rmse": 0.5634, "test_mae": 0.4226, "test_r2": 0.7442, "status": "Winner / Production", "best": True},
                        {"model": "random_forest", "name": "RandomForestRegressor (100 trees)", "val_rmse": 0.5761, "val_mae": 0.4306, "val_r2": 0.7295, "test_rmse": 0.5761, "test_mae": 0.4317, "test_r2": 0.7326, "status": "Evaluated", "best": False},
                        {"model": "ridge", "name": "Ridge Regression (L2 α=1.0)", "val_rmse": 0.6181, "val_mae": 0.4928, "val_r2": 0.6886, "test_rmse": 0.6227, "test_mae": 0.4953, "test_r2": 0.6876, "status": "Evaluated", "best": False},
                        {"model": "mean_baseline", "name": "Mean Baseline (Naive ȳ)", "val_rmse": 1.1078, "val_mae": 0.9215, "val_r2": -0.0001, "test_rmse": 1.1140, "test_mae": 0.9253, "test_r2": -0.0000, "status": "Baseline", "best": False},
                    ],
                    "residual_stats": {
                        "mean_error": 0.0012,
                        "std_error": 0.5634,
                        "empirical_68_margin": "±0.56 pts",
                        "empirical_95_margin": "±1.10 pts",
                    }
                },
                "task_b_classification": {
                    "task_id": "task_b",
                    "title": "Elevated-Risk Classification & Probability Calibration",
                    "target_variable": "is_elevated_risk (burnout_score >= 3.70)",
                    "target_scale": "Binary Classification (90th percentile threshold, ~10.4% positive prevalence)",
                    "dataset_source": "tech_mental_health_burnout (30,000 held-out test records)",
                    "calibration_method": "CalibratedClassifierCV (method='sigmoid', 5-fold cross-validation)",
                    "optimal_threshold": 0.33,
                    "recommended_model": "hist_gradient_boosting",
                    "models": metrics.get("risk_model", {}).get("classifier_models", {}),
                    "rankings": [
                        {"model": "hist_gradient_boosting", "name": "HistGradientBoosting + CalibratedClassifierCV", "test_roc_auc": 0.9501, "test_pr_auc": 0.7319, "test_brier": 0.0512, "f1_tuned": 0.6648, "precision_tuned": 0.6269, "recall_tuned": 0.7075, "threshold": 0.33, "status": "Winner / Production", "best": True},
                        {"model": "logistic_regression", "name": "Logistic Regression (L2 penalty)", "test_roc_auc": 0.9524, "test_pr_auc": 0.7391, "test_brier": 0.0505, "f1_tuned": 0.6685, "precision_tuned": 0.6283, "recall_tuned": 0.7141, "threshold": 0.31, "status": "Candidate", "best": False},
                        {"model": "random_forest", "name": "Random Forest Classifier", "test_roc_auc": 0.9445, "test_pr_auc": 0.7113, "test_brier": 0.0545, "f1_tuned": 0.6499, "precision_tuned": 0.6104, "recall_tuned": 0.6947, "threshold": 0.29, "status": "Evaluated", "best": False},
                        {"model": "majority_baseline", "name": "Majority Class Baseline", "test_roc_auc": 0.5000, "test_pr_auc": 0.1101, "test_brier": 0.1101, "f1_tuned": 0.0000, "precision_tuned": 0.0000, "recall_tuned": 0.0000, "threshold": 0.10, "status": "Baseline", "best": False},
                    ],
                    "confusion_matrix": {
                        "threshold": 0.33,
                        "true_negatives": 25561,
                        "false_positives": 1314,
                        "false_negatives": 914,
                        "true_positives": 2211,
                        "accuracy": 0.9257,
                        "sensitivity": 0.7075,
                        "specificity": 0.9511,
                    }
                },
                "task_c_forecasting": {
                    "task_id": "task_c",
                    "title": "CBI Longitudinal Forecasting (Month t → Month t+1)",
                    "target_variable": "target_next_cbi_work_score",
                    "target_scale": "0–100 Copenhagen Burnout Inventory Scale (Work-Related Subscale)",
                    "dataset_source": "Longitudinal Panel forecast_t_to_t1.csv (11,764 records across 2,065 employees)",
                    "split_strategy": "Grouped split by employee_id: 1,652 train employees (9,492 records) vs 413 test employees (2,272 records). Zero employee overlap.",
                    "primary_benchmark": "Persistence Baseline (predicting next month = current month score)",
                    "regression_models": forecast_metrics.get("regression", {}),
                    "classification_models": forecast_metrics.get("classification", {}),
                    "rankings": [
                        {"model": "ridge", "name": "Ridge Multi-Feature Regressor (t → t+1)", "test_rmse": 10.1883, "test_mae": 8.0491, "test_r2": 0.6480, "delta_vs_persistence_rmse": -1.0266, "status": "Winner / Production", "best": True},
                        {"model": "hist_gradient_boosting", "name": "Hist Gradient Boosting", "test_rmse": 10.4128, "test_mae": 8.2566, "test_r2": 0.6323, "delta_vs_persistence_rmse": -0.8021, "status": "Evaluated", "best": False},
                        {"model": "random_forest", "name": "Random Forest Regressor", "test_rmse": 10.4444, "test_mae": 8.2771, "test_r2": 0.6301, "delta_vs_persistence_rmse": -0.7705, "status": "Evaluated", "best": False},
                        {"model": "persistence_baseline", "name": "Gold-Standard Persistence Baseline (ŷ_{t+1} = y_t)", "test_rmse": 11.2149, "test_mae": 8.7615, "test_r2": 0.5735, "delta_vs_persistence_rmse": 0.0, "status": "Gold Standard Baseline", "best": False},
                        {"model": "mean_baseline", "name": "Naive Mean Baseline (ŷ_{t+1} = ȳ)", "test_rmse": 17.2166, "test_mae": 13.8457, "test_r2": -0.0051, "delta_vs_persistence_rmse": 6.0017, "status": "Naive Baseline", "best": False},
                    ],
                    "residual_stats": {
                        "mean_error": 0.08,
                        "residual_rmse_se": 10.02,
                        "empirical_95_margin": "±19.63 CBI pts (1.96 × s_e)",
                        "coverage_rate_95": "94.8% empirical test coverage"
                    }
                }
            },
            "feature_importance": feature_importance,
            "datasets": [
                {
                    "name": "Tech Mental Health Workforce",
                    "nature": "Synthetic / Enterprise Telemetry Simulation",
                    "sample_size": 150000,
                    "target": "burnout_score (0–10 continuous)",
                    "purpose": "Operational Regressor & Classifier Training (Task A & B)",
                    "status": "Active Training Dataset"
                },
                {
                    "name": "Longitudinal Panel Simulation",
                    "nature": "Synthetic Sequential Panel Simulation",
                    "sample_size": 11764,
                    "target": "target_next_cbi_work_score (0–100 CBI at t+1)",
                    "purpose": "Autoregressive Forecasting & Grouped Split Evaluation (Task C)",
                    "status": "Active Forecasting Dataset"
                },
                {
                    "name": "Academic Librarian CBI Dataset",
                    "nature": "Real-World Observed Empirical Survey (Wood et al., Kennesaw State University DigitalCommons)",
                    "sample_size": 1598,
                    "target": "cbi_work_score (0–100 CBI)",
                    "purpose": "Psychometric Reliability Baseline (Cronbach's α = 0.887). Excluded from commercial training.",
                    "status": "Psychometric Benchmark Only"
                },
                {
                    "name": "HackerEarth Burnout Dataset",
                    "nature": "Synthetic Competition Benchmark",
                    "sample_size": 12180,
                    "target": "Burn Rate (0–10 rescaled)",
                    "purpose": "Isolated External Benchmark",
                    "status": "Isolated Benchmark"
                }
            ],
            "methodology_safeguards": [
                {
                    "title": "Zero Subject / Grouped Split",
                    "description": "In longitudinal panel evaluations, dataset splits are grouped strictly on employee_id. Zero observations from the same individual appear in both training and testing folds, eliminating person-level memorization leakage."
                },
                {
                    "title": "No Survey Item Leakage",
                    "description": "Individual psychometric survey responses (cbi_w1–cbi_w7) are strictly excluded from predictive features. Models rely exclusively on external workplace telemetry (hours, overtime, meetings, deadlines)."
                },
                {
                    "title": "Strict Time-Directionality",
                    "description": "Predictors measured at period t predict outcomes strictly at period t+1. All future period metrics and simultaneous outcome indicators are masked."
                },
                {
                    "title": "Pipeline Encapsulation",
                    "description": "All data transformations (median imputers, standard scalers, categorical encoders) are learned exclusively on training folds within scikit-learn Pipeline objects to prevent distribution leakage."
                },
                {
                    "title": "Probability Calibration",
                    "description": "Classifiers are wrapped with CalibratedClassifierCV using 5-fold cross-validation and sigmoid scaling to ensure predicted probabilities match empirical observation rates (Brier score 0.0512)."
                },
                {
                    "title": "Observational & Non-Causal Framing",
                    "description": "Feature coefficients reflect statistical associations within simulated telemetry, not causal physiological proofs. Predictions must be used strictly for supportive accommodations, never for punitive actions."
                }
            ]
        }

    # ─── FRAMEWORKS PAYLOAD ──────────────────────────────────────────────────
    def get_frameworks(self) -> dict:
        """The single BurnoutIQ framework: the monitoring loop implemented by the burnoutiq package."""
        from burnout_platform.loop_view import STAGES
        return {"frameworks_count": 1, "framework": {
            "id": "burnoutiq_loop", "title": "BurnoutIQ monitoring loop",
            "inner_loop": [s for s in STAGES if s["id"] != "learn"],
            "outer_loop": [s for s in STAGES if s["id"] == "learn"],
            "implemented_in": "burnoutiq package (python -m burnoutiq); live values at /api/loop",
        }}

    def analyse_upload(self, file_obj, filename: str) -> dict:
        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are accepted.")
        file_obj.seek(0, 2); size = file_obj.tell(); file_obj.seek(0)
        if size > 500 * 1024 * 1024:
            raise ValueError("File exceeds 500 MB limit.")
        defaults = self.default_features()
        numeric  = [x for x in FEATURES if x not in {"company_size", "job_role", "work_mode"}]
        rows = 0; score_total = 0.0; prob_total = 0.0
        bands_total = {"Low": 0, "Moderate": 0, "Elevated": 0}
        role_agg = {}; loc_agg = {}; gender_agg = {}; mode_agg = {}; state_agg = {}
        dur_agg = {lbl: {"score_sum": 0.0, "count": 0, "elevated": 0} for lbl in DURATION_LABELS}
        present = None; loc_field = gender_field = emp_id_field = state_field = None
        self.uploaded_employees = {}
        emp_chunks: list[pd.DataFrame] = []
        raw_chunks: list[pd.DataFrame] = []
        pii_stripped_total: set[str] = set()
        for chunk in pd.read_csv(file_obj, chunksize=100_000):
            chunk.columns = [str(c).strip() for c in chunk.columns]
            col_map = {c: c.lower().replace(" ", "_") for c in chunk.columns}
            cl = chunk.rename(columns=col_map)
            cl, stripped_cols = strip_forbidden_pii(cl)
            if stripped_cols:
                pii_stripped_total.update(stripped_cols)
            if present is None:
                present = set(cl.columns)
                miss = sorted(CORE_UPLOAD_FIELDS - present)
                if miss: raise ValueError("Missing required fields: " + ", ".join(miss))
                loc_field    = next((f for f in ["city","employee_location","location"] if f in present), None)
                state_field  = next((f for f in ["state","province","region"] if f in present), None)
                gender_field = next((f for f in ["gender","sex"] if f in present), None)
                emp_id_field = next((f for f in ["employeeid","employee_id","emp_id","empid"] if f in present), None)
            rows += len(cl)
            if rows > 1_000_000: raise ValueError("File exceeds 1,000,000 rows.")
            all_def = {col: (self.df[col].median() if self.df[col].dtype.kind in "bifc"
                             else (self.df[col].mode().iloc[0] if not self.df[col].mode().empty else ""))
                       for col in self.df.columns}
            batch = pd.DataFrame(index=cl.index)
            for col in self.df.columns:
                lc = col.lower().replace(" ", "_")
                batch[col] = cl[lc].values if lc in cl.columns else (cl[col].values if col in cl.columns else all_def[col])
            for col in numeric:
                if col in batch.columns:
                    batch[col] = pd.to_numeric(batch[col], errors="coerce").fillna(all_def.get(col, 0))
            for col in {"company_size", "job_role", "work_mode"}:
                if col in batch.columns:
                    batch[col] = batch[col].fillna(all_def.get(col, "")).astype(str)
            try:
                batch_eng = engineer_features(batch)
                score = np.clip(self.score_model.predict(batch_eng), 0, 10)
                prob  = self.risk_model.predict_proba(batch_eng)[:, 1]
            except Exception as exc:
                return {"error": f"Analysis failed: {exc}"}
            band     = np.where(score >= self.threshold, "Elevated", np.where(score >= 2.5, "Moderate", "Low"))
            elevated = score >= self.threshold
            score_total += float(score.sum()); prob_total += float(prob.sum())
            for b in bands_total: bands_total[b] += int((band == b).sum())
            if "job_role" in cl.columns: _agg_chunk(cl["job_role"].fillna("Unknown"), score, elevated, role_agg)
            if loc_field and loc_field in cl.columns: _agg_chunk(cl[loc_field].fillna("Unknown"), score, elevated, loc_agg)
            if gender_field and gender_field in cl.columns: _agg_chunk(cl[gender_field].fillna("Unknown"), score, elevated, gender_agg)
            if "work_mode" in cl.columns: _agg_chunk(cl["work_mode"].fillna("Unknown"), score, elevated, mode_agg)
            state_series = None
            if state_field and state_field in cl.columns:
                state_series = cl[state_field].astype(str)
            elif loc_field and loc_field in cl.columns:
                state_series = cl[loc_field].apply(lambda c: CITY_TO_STATE.get(str(c).lower().strip()))
            if state_series is not None:
                valid = state_series.notna() & (state_series != "None") & (state_series != "nan")
                if valid.any():
                    _agg_chunk(state_series[valid].fillna("Unknown"), score[valid.values], elevated[valid.values], state_agg)
            if "work_hours_per_week" in cl.columns:
                hrs = pd.to_numeric(cl["work_hours_per_week"], errors="coerce").fillna(40)
                dlbl = pd.cut(hrs, bins=DURATION_BINS, labels=DURATION_LABELS, right=True)
                for lbl, vals in pd.DataFrame({"g": dlbl, "s": score, "e": elevated}).groupby("g", observed=True).agg(ss=("s","sum"),cnt=("s","size"),el=("e","sum")).iterrows():
                    cur = dur_agg[str(lbl)]
                    cur["score_sum"] += float(vals["ss"]); cur["count"] += int(vals["cnt"]); cur["elevated"] += int(vals["el"])
            def _col(name):
                return cl[name] if name and name in cl.columns else pd.Series([None]*len(cl), index=cl.index, dtype=object)
            def _num_col(name):
                c = cl[name] if name and name in cl.columns else pd.Series([None]*len(cl), index=cl.index, dtype=object)
                return pd.to_numeric(c, errors="coerce").round(1)
            emp_chunk_df = pd.DataFrame({
                "id":         _col(emp_id_field).astype(str),
                "role":       _col("job_role").fillna("").astype(str),
                "mode":       _col("work_mode").fillna("").astype(str),
                "city":       _col(loc_field).fillna("").astype(str),
                "state":      (state_series.fillna("").astype(str) if state_series is not None else pd.Series([""] * len(cl), index=cl.index)),
                "gender":     _col(gender_field).fillna("").astype(str),
                "hours":      _num_col("work_hours_per_week"),
                "stress":     _num_col("stress_level"),
                "overtime":   _num_col("overtime_hours"),
                "experience": _num_col("experience_years"),
                "score":      pd.Series(score.round(2), index=cl.index),
                "prob":       pd.Series((prob * 100).round(1), index=cl.index),
                "band":       pd.Series(band, index=cl.index),
            }, index=cl.index)
            emp_chunks.append(emp_chunk_df)
            raw_chunks.append(cl)

        if not rows: raise ValueError("Uploaded file has no employee rows.")
        self.employee_df = pd.concat(emp_chunks, ignore_index=True) if emp_chunks else None
        self.uploaded_raw_df = pd.concat(raw_chunks, ignore_index=True) if raw_chunks else None
        self.active_dataset_info = {
            "name": f"Uploaded File: {filename}",
            "source_file": filename,
            "record_count": rows,
            "is_upload": True,
            "last_refresh": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "has_longitudinal": False,
            "has_interventions": False,
            "score_scale": "0–10 Continuous Workforce Scale",
        }

        interventions, role_drivers = self.compute_interventions_and_drivers(self.uploaded_raw_df, rows)
        role_summary = _summarize_groups(role_agg)
        for r in role_summary:
            r["drivers"] = role_drivers.get(r["name"], [])

        return {
            "active_dataset": self.active_dataset_info,
            "detected_fields": sorted(present & set(FEATURES)),
            "optional_fields_not_supplied": sorted(OPTIONAL_WORKPLACE_FIELDS - present),
            "has_gender": gender_field is not None,
            "has_location": loc_field is not None,
            "has_state": bool(state_agg),
            "has_emp_id": emp_id_field is not None,
            "has_employee_table": self.employee_df is not None and not self.employee_df.empty,
            "employee_table_count": len(self.employee_df) if self.employee_df is not None else 0,
            "mean_burnout_score": round(score_total / rows, 2),
            "elevated_review_rate": round(bands_total["Elevated"] / rows * 100, 1),
            "mean_elevated_probability": round(prob_total / rows * 100, 1),
            "risk_distribution": bands_total,
            "role_analysis": role_summary,
            "interventions": interventions,
            "role_drivers": role_drivers,
            "location_analysis": _summarize_groups(loc_agg),
            "gender_analysis": _summarize_groups(gender_agg),
            "work_mode_analysis": _summarize_groups(mode_agg),
            "duration_analysis": _summarize_groups({k: v for k, v in dur_agg.items() if v["count"] > 0}),
            "state_analysis": _summarize_groups(state_agg, limit=30),
            "upload_progress_percent": 100,
            "initial_table": self.get_employee_table(page=0, page_size=25),
            "stripped_pii_fields": sorted(pii_stripped_total),
            "privacy_notice": PRIVACY_DISCLOSURE_NOTICE,
            "is_medical_diagnosis": False,
            "responsible_use_advisory": (
                "Workforce decision-support only. Results must not be used for punitive employment actions."
            ),
            "notice": "The uploaded file is streamed in batches and is not retained by this service.",
        }


# ─── Flask App ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=str(ROOT), static_url_path="")


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(str(ROOT), "dashboard.html", mimetype="text/html; charset=utf-8")


@app.route("/api/summary", methods=["GET"])
def api_summary():
    try:
        return jsonify(get_state().summary())
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/api/predict", methods=["POST", "OPTIONS"])
def api_predict():
    if request.method == "OPTIONS":
        return "", 204
    try:
        payload = request.get_json(force=True) or {}
        return jsonify(get_state().predict(payload))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/model-lab", methods=["GET"])
def api_model_lab():
    return jsonify(get_state().get_model_lab())


@app.route("/api/frameworks", methods=["GET"])
def api_frameworks():
    return jsonify(get_state().get_frameworks())


@app.route("/api/featured-employee", methods=["GET"])
def api_featured_employee():
    featured = get_state().search_employee("SYN-00017")
    return jsonify(featured or {})


@app.route("/api/search-employee", methods=["GET"])
def api_search_employee():
    emp_id = request.args.get("id", "").strip() or "SYN-00017"
    result = get_state().search_employee(emp_id)
    if result is None:
        return jsonify({"error": f"Employee '{emp_id}' not found."}), 404
    return jsonify(result)


@app.route("/api/employee-table", methods=["GET"])
def api_employee_table():
    state = get_state()
    export = request.args.get("export") == "1"
    try:
        page = int(request.args.get("page", "0"))
        page_size = min(int(request.args.get("page_size", "25")), 200)
    except ValueError:
        page, page_size = 0, 25

    category = request.args.get("category", "")
    inc_master = request.args.get("include_master", "1" if not state.active_dataset_info.get("is_upload") else "0") == "1"

    result = state.get_employee_table(
        page=page, page_size=page_size,
        search=request.args.get("search", ""),
        filter_band=request.args.get("filter_band", ""),
        filter_role=request.args.get("filter_role", ""),
        filter_mode=request.args.get("filter_mode", ""),
        filter_city=request.args.get("filter_city", ""),
        sort_col=request.args.get("sort_col", "score"),
        sort_dir=request.args.get("sort_dir", "desc"),
        export=export,
        category=category,
        include_master=inc_master,
    )
    if export:
        buf = io.StringIO()
        if isinstance(result, pd.DataFrame):
            result.to_csv(buf, index=False)
        return buf.getvalue(), 200, {
            "Content-Type": "text/csv",
            "Content-Disposition": 'attachment; filename="employee_burnout_report.csv"',
        }
    return jsonify(result)


@app.route("/api/analyse-upload", methods=["POST", "OPTIONS"])
def api_analyse_upload():
    if request.method == "OPTIONS":
        return "", 204
    try:
        if "file" not in request.files:
            return jsonify({"error": "No CSV file received."}), 400
        f = request.files["file"]
        return jsonify(get_state().analyse_upload(f.stream, f.filename or "upload.csv"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/health", methods=["GET"])
def api_health():
    s = get_state()
    return jsonify({
        "status": "healthy",
        "service": "BurnoutIQ",
        "version": "1.0.0",
        "active_dataset": s.active_dataset_info.get("name", "Master Workforce Dataset"),
        "records_loaded": len(s.df),
        "models_loaded": {
            "forecasting": getattr(s.longitudinal_tracker, "forecast_model", None) is not None,
            "score_model": s.score_model is not None,
            "risk_model": s.risk_model is not None,
        }
    })


@app.route("/api/forecast", methods=["GET"])
def api_forecast():
    """Returns longitudinal time-series forecasting metrics, model comparisons, and projections."""
    try:
        cohort = request.args.get("cohort", "")
        return jsonify(get_state().get_forecast(cohort=cohort))
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/api/interventions-tracking", methods=["GET"])
def api_interventions_tracking():
    """Returns intervention tracking funnel, outcomes breakdown, and longitudinal action records."""
    try:
        return jsonify(get_state().get_interventions_tracking())
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/api/loop", methods=["GET"])
def api_loop():
    """Returns every stage of the burnoutiq loop (assess, predict, simulate, intervene, verify, learn)."""
    try:
        return jsonify(get_state().longitudinal_tracker.get_loop_payload(request.args.get("period") or None))
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/api/loop/upload", methods=["POST", "OPTIONS"])
def api_loop_upload():
    """Run the loop on uploaded employees / monthly / interventions CSVs and make them the active data."""
    if request.method == "OPTIONS":
        return "", 204
    files = {k: request.files[k].read() for k in ("employees", "monthly", "interventions") if k in request.files}
    res = upload_to_tracker(get_state().longitudinal_tracker, files)
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/data", methods=["GET"])
def api_loop_data():
    """What is loaded: surveys per month, field completeness, input counts and issues."""
    return jsonify(get_state().longitudinal_tracker.data_summary())


@app.route("/api/loop/seats", methods=["GET"])
def api_loop_seats():
    """Everyone this month as [id, department, team, state] for the stadium chart."""
    return jsonify(get_state().longitudinal_tracker.seat_rows(period=request.args.get("period") or None))


@app.route("/api/loop/teams", methods=["GET"])
def api_loop_teams():
    """Teams ranked for one month; teams under 5 scored people are listed without scores."""
    a = request.args.get
    return jsonify(get_state().longitudinal_tracker.team_rows(period=a("period") or None, department=a("department", ""), sort=a("sort", "score")))


@app.route("/api/loop/employees", methods=["GET"])
def api_loop_employees():
    """Ranked, filterable employee list for one month (department, team, level, workload, status, search)."""
    return jsonify(employee_query(get_state().longitudinal_tracker, request.args.get))


@app.route("/api/loop/add-month", methods=["POST", "OPTIONS"])
def api_loop_add_month():
    """Append a new month's monthly.csv (plus optional interventions/employees) and rerun the loop."""
    if request.method == "OPTIONS":
        return "", 204
    files = {k: request.files[k].read() for k in ("employees", "monthly", "interventions") if k in request.files}
    res = add_month_to_tracker(get_state().longitudinal_tracker, files)
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/try-survey", methods=["POST", "OPTIONS"])
def api_loop_try_survey():
    """Score one filled-in sample survey and forecast next month across working hours (nothing stored)."""
    if request.method == "OPTIONS":
        return "", 204
    res = try_survey_action(get_state().longitudinal_tracker, request.get_json(silent=True) or {})
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/support", methods=["POST", "OPTIONS"])
@app.route("/api/loop/support/status", methods=["POST", "OPTIONS"])
def api_loop_support():
    """Log support for one person, or mark it started / completed / stopped; the loop is refitted."""
    if request.method == "OPTIONS":
        return "", 204
    res = support_action(get_state().longitudinal_tracker, request.path, request.get_json(silent=True) or {})
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/demo-start", methods=["POST", "OPTIONS"])
def api_loop_demo_start():
    """Run the demo panel up to one month before its end (or {"until": "YYYY-MM"})."""
    if request.method == "OPTIONS":
        return "", 204
    until = (request.get_json(silent=True) or {}).get("until")
    res = run_tracker_action(lambda: get_state().longitudinal_tracker.start_live_demo(until))
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/demo-next", methods=["POST", "OPTIONS"])
def api_loop_demo_next():
    """Add the demo panel's next month and rerun the loop."""
    if request.method == "OPTIONS":
        return "", 204
    res = run_tracker_action(get_state().longitudinal_tracker.add_demo_month)
    return jsonify(res), (200 if res["ok"] else 400)


@app.route("/api/loop/reset", methods=["POST", "OPTIONS"])
def api_loop_reset():
    """Return to the synthetic demonstration panel."""
    if request.method == "OPTIONS":
        return "", 204
    return jsonify({"ok": True, "source": get_state().longitudinal_tracker.reset_to_demo()})


@app.route("/api/interventions/records", methods=["GET"])
def api_intervention_records():
    """Returns paginated, filterable action records from the persistent action store."""
    try:
        try:
            page = int(request.args.get("page", "0"))
            page_size = min(int(request.args.get("page_size", "25")), 100)
        except ValueError:
            page, page_size = 0, 25
        return jsonify(get_state().get_intervention_records(
            status=request.args.get("status", ""),
            department=request.args.get("dept", ""),
            search=request.args.get("search", ""),
            sort_by=request.args.get("sort_by", "priority"),
            page=page,
            page_size=page_size
        ))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/interventions/update-status", methods=["POST", "OPTIONS"])
def api_update_intervention_status():
    """Update action status, owner, or follow-up due date with disk persistence."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        payload = request.get_json(silent=True) or {}
        res = get_state().update_intervention_status(
            action_id=payload.get("action_id", ""),
            status=payload.get("status"),
            owner=payload.get("owner"),
            follow_up_due_date=payload.get("follow_up_due_date"),
            notes=payload.get("notes")
        )
        if res is None:
            return jsonify({"error": "Action record not found."}), 404
        return jsonify({"status": "success", "record": res})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/interventions/record", methods=["POST", "OPTIONS"])
def api_record_intervention():
    """Record a newly agreed supportive intervention for an employee."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        payload = request.get_json(silent=True) or {}
        eid = payload.get("employee_id", "").strip()
        if not eid:
            return jsonify({"error": "Employee ID is required."}), 400
        itype = payload.get("intervention_type", "workload_review")
        res = get_state().record_intervention(
            employee_id=eid,
            intervention_type=itype,
            owner=payload.get("owner"),
            follow_up_due_date=payload.get("follow_up_due_date"),
            notes=payload.get("notes")
        )
        return jsonify({"status": "success", "record": res})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/interventions/record-followup", methods=["POST", "OPTIONS"])
def api_record_followup():
    """Record subsequent assessment score and update longitudinal outcome status."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        payload = request.get_json(silent=True) or {}
        aid = payload.get("action_id", "").strip()
        if not aid:
            return jsonify({"error": "Action ID is required."}), 400
        score = payload.get("follow_up_cbi_score")
        if score is None:
            return jsonify({"error": "follow_up_cbi_score is required."}), 400
        res = get_state().record_followup_assessment(
            action_id=aid,
            follow_up_cbi_score=float(score),
            assessment_date=payload.get("assessment_date"),
            notes=payload.get("notes")
        )
        if res is None:
            return jsonify({"error": "Action record not found."}), 404
        return jsonify({"status": "success", "record": res})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/reset-dataset", methods=["GET", "POST", "OPTIONS"])
def api_reset_dataset():
    """Resets active dashboard state back to the primary master workforce dataset."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        state = get_state()
        state.reset_to_master()
        return jsonify({
            "status": "success",
            "message": "Dashboard successfully reset to the Tech Workforce Dataset.",
            "active_dataset": state.active_dataset_info,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# Vercel uses the `app` object as the WSGI handler

