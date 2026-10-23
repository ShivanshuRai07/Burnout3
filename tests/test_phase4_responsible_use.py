"""Phase 4 Test Suite — Responsible Use, Workplace Insights, Privacy Safeguards & Pilot Readiness.

Verifies:
1. Workplace insight indicator translation (Workload, Meetings, Deadlines, Rest)
2. Actionable, non-medical operational suggestions mapped from numerical telemetry
3. Clear distinction between model predictions, observed data, and suggested actions
4. Quantification of prediction uncertainty (RMSE ±0.56 margin)
5. Privacy safeguards: automated PII stripping, cell suppression (k >= 5), masked employee IDs
6. API behavior: privacy-preserving endpoints, stripped PII reporting, responsible use notices
7. Pilot readiness documentation completeness and governance criteria
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from burnout_platform.insights import (
    assess_workplace_indicators,
    generate_actionable_suggestions,
    build_workplace_insight_bundle,
    ESTIMATION_ERROR_MARGIN,
    PROHIBITED_USES,
)
from burnout_platform.privacy import (
    is_pii_field,
    strip_forbidden_pii,
    mask_employee_id,
    apply_cell_suppression,
    PRIVACY_DISCLOSURE_NOTICE,
    MIN_AGGREGATION_CELL_SIZE,
)
from burnout_platform.validation import (
    NON_DIAGNOSTIC_NOTICE,
    EVALUATION_THRESHOLD,
    PROBABILITY_THRESHOLD,
)
from dashboard_server import DashboardState
import api.index as vercel_app


@pytest.fixture(scope="module")
def api_client():
    return vercel_app.app.test_client()


@pytest.fixture(scope="module")
def dashboard_state() -> DashboardState:
    artifacts = Path("artifacts").resolve()
    pkl_path = artifacts / "master_workforce_dataset.pkl.gz"
    csv_path = artifacts / "master_workforce_dataset.csv"
    data_path = pkl_path if pkl_path.exists() else csv_path
    return DashboardState(data_path=data_path, artifacts=artifacts)


# ─── 1. WORKPLACE INSIGHT INDICATORS ────────────────────────────────────────

def test_workplace_indicators_elevated_intensity():
    """Verify high hours and overtime translate to 'Elevated' workload status."""
    obs = {"work_hours_per_week": 55.0, "overtime_hours": 10.0}
    indicators = assess_workplace_indicators(obs)
    assert indicators["workload_intensity"]["status"] == "Elevated"
    assert "55h/wk" in indicators["workload_intensity"]["summary"]


def test_workplace_indicators_meeting_density():
    """Verify high daily meetings translate to 'High' calendar fragmentation status."""
    obs = {"meetings_per_day": 5.5}
    indicators = assess_workplace_indicators(obs)
    assert indicators["meeting_density"]["status"] == "High"
    assert "fragmentation" in indicators["meeting_density"]["summary"]


def test_workplace_indicators_delivery_friction():
    """Verify missed deadlines translate to 'Friction' milestone status."""
    obs = {"deadlines_missed": 3.0}
    indicators = assess_workplace_indicators(obs)
    assert indicators["delivery_friction"]["status"] == "Friction"


def test_workplace_indicators_rest_boundary():
    """Verify short sleep intervals translate to 'Constrained' rest boundary."""
    obs = {"sleep_hours": 5.0}
    indicators = assess_workplace_indicators(obs)
    assert indicators["rest_boundary"]["status"] == "Constrained"


# ─── 2. ACTIONABLE OPERATIONAL SUGGESTIONS ───────────────────────────────────

def test_suggestions_overtime_guardrail():
    """Verify overtime >= 6h derives specific overtime guardrail recommendation."""
    obs = {"overtime_hours": 8.0}
    suggestions = generate_actionable_suggestions(obs, risk_band="Elevated")
    overtime_actions = [s for s in suggestions if s["category"] == "Overtime Guardrail"]
    assert len(overtime_actions) == 1
    assert "Cap individual overtime at maximum 4h/week" in overtime_actions[0]["action"]


def test_suggestions_meeting_detox():
    """Verify heavy meeting load derives focus-block / meeting-hygiene recommendation."""
    obs = {"meetings_per_day": 5.0}
    suggestions = generate_actionable_suggestions(obs, risk_band="Elevated")
    meeting_actions = [s for s in suggestions if s["category"] == "Meeting Hygiene"]
    assert len(meeting_actions) == 1
    assert "meeting-free" in meeting_actions[0]["action"].lower()


def test_suggestions_non_medical_content():
    """Verify all suggestions are strictly operational and contain no clinical prescriptions."""
    obs = {
        "work_hours_per_week": 60.0,
        "overtime_hours": 12.0,
        "meetings_per_day": 6.0,
        "deadlines_missed": 3.0,
        "stress_level": 9.0,
    }
    suggestions = generate_actionable_suggestions(obs, risk_band="Elevated")
    medical_terms = ["medication", "therapy", "antidepressant", "psychiatrist", "clinical", "diagnose"]

    for s in suggestions:
        action_text = s["action"].lower()
        rationale_text = s["rationale"].lower()
        for term in medical_terms:
            assert term not in action_text, f"Medical term '{term}' found in action: {action_text}"
            assert term not in rationale_text, f"Medical term '{term}' found in rationale: {rationale_text}"


def test_suggestions_low_risk_maintenance():
    """Verify low-risk profile produces workload maintenance suggestion."""
    obs = {"work_hours_per_week": 38.0, "overtime_hours": 1.0, "meetings_per_day": 2.0}
    suggestions = generate_actionable_suggestions(obs, risk_band="Low")
    assert any(s["category"] == "Workload Maintenance" for s in suggestions)


# ─── 3. EXPLICIT SEPARATION & UNCERTAINTY QUANTIFICATION ─────────────────────

def test_insight_bundle_structure_and_uncertainty():
    """Verify explicit separation of prediction, observed telemetry, and suggestions."""
    observed = {"work_hours_per_week": 44.0, "overtime_hours": 4.0, "meetings_per_day": 3.0}
    bundle = build_workplace_insight_bundle(
        observed_inputs=observed,
        score=3.20,
        prob=22.5,
        risk_band="Moderate",
        threshold=3.70,
    )

    # 1. Distinct Tiers
    assert "model_prediction" in bundle
    assert "observed_workplace_telemetry" in bundle
    assert "workplace_indicators" in bundle
    assert "suggested_actions" in bundle
    assert "responsible_use_safeguards" in bundle

    # 2. Uncertainty Quantification
    pred = bundle["model_prediction"]
    assert pred["estimated_burnout_score"] == 3.20
    assert pred["uncertainty_interval"] == [2.64, 3.76]
    assert pred["estimation_rmse_margin"] == ESTIMATION_ERROR_MARGIN

    # 3. Responsible Use Safeguards
    safeguards = bundle["responsible_use_safeguards"]
    assert safeguards["is_medical_diagnosis"] is False
    assert safeguards["decision_support_only"] is True
    assert len(safeguards["prohibited_actions"]) >= 4


# ─── 4. PRIVACY SAFEGUARDS & DATA SECURITY ──────────────────────────────────

def test_is_pii_field_detection():
    """Verify PII detection identifies sensitive identifiers and permits workplace telemetry."""
    # Forbidden PII
    assert is_pii_field("full_name") is True
    assert is_pii_field("employee_name") is True
    assert is_pii_field("email_address") is True
    assert is_pii_field("phone_number") is True
    assert is_pii_field("ssn") is True
    assert is_pii_field("aadhaar_card") is True
    assert is_pii_field("monthly_salary") is True
    assert is_pii_field("medical_diagnosis") is True

    # Permitted Telemetry
    assert is_pii_field("work_hours_per_week") is False
    assert is_pii_field("overtime_hours") is False
    assert is_pii_field("meetings_per_day") is False
    assert is_pii_field("deadlines_missed") is False
    assert is_pii_field("job_role") is False
    assert is_pii_field("work_mode") is False


def test_strip_forbidden_pii_from_dataframe():
    """Verify PII columns are stripped from DataFrame during upload ingestion."""
    df_raw = pd.DataFrame({
        "employee_id": ["EMP001", "EMP002"],
        "full_name": ["Alice Smith", "Bob Jones"],
        "email": ["alice@company.com", "bob@company.com"],
        "salary": [120000, 115000],
        "work_hours_per_week": [40, 45],
        "overtime_hours": [2, 5],
        "job_role": ["Software Engineer", "Devops"],
        "work_mode": ["Remote", "Hybrid"],
    })

    sanitized_df, stripped = strip_forbidden_pii(df_raw)

    assert set(stripped) == {"full_name", "email", "salary"}
    assert "full_name" not in sanitized_df.columns
    assert "email" not in sanitized_df.columns
    assert "salary" not in sanitized_df.columns
    assert "work_hours_per_week" in sanitized_df.columns
    assert len(sanitized_df) == 2


def test_mask_employee_id():
    """Verify employee identifiers are masked for logs and non-privileged displays."""
    assert mask_employee_id("tech_12345") == "te***45"
    assert mask_employee_id("EMP-9876") == "EM***76"
    assert mask_employee_id(None) == "EMP-ANONYMOUS"


def test_k_anonymity_cell_suppression():
    """Verify cell suppression triggers when employee count is below k=5."""
    assert apply_cell_suppression(count=2, min_k=MIN_AGGREGATION_CELL_SIZE) is True
    assert apply_cell_suppression(count=4, min_k=MIN_AGGREGATION_CELL_SIZE) is True
    assert apply_cell_suppression(count=5, min_k=MIN_AGGREGATION_CELL_SIZE) is False
    assert apply_cell_suppression(count=20, min_k=MIN_AGGREGATION_CELL_SIZE) is False
    assert apply_cell_suppression(count=0, min_k=MIN_AGGREGATION_CELL_SIZE) is False


# ─── 5. API PRIVACY & RESPONSIBLE USE INTEGRATION ────────────────────────────

def test_api_predict_returns_phase4_insights_and_safeguards(api_client):
    """Verify POST /api/predict returns full insight bundle, uncertainty, and safeguards."""
    resp = api_client.post("/api/predict", json={
        "work_hours_per_week": 50,
        "overtime_hours": 8,
        "meetings_per_day": 5,
        "deadlines_missed": 2,
        "stress_level": 7.5,
        "job_role": "Backend Developer",
        "work_mode": "Hybrid",
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)

    # Core Phase 3 keys preserved
    assert "burnout_score" in data
    assert "elevated_risk_probability" in data
    assert "risk_band" in data

    # Phase 4 Workplace Insights & Safeguards
    assert "uncertainty_interval" in data
    assert len(data["uncertainty_interval"]) == 2
    assert "workplace_indicators" in data
    assert "suggested_actions" in data
    assert len(data["suggested_actions"]) >= 1
    assert "responsible_use_safeguards" in data
    assert data["responsible_use_safeguards"]["decision_support_only"] is True
    assert data["is_medical_diagnosis"] is False
    assert NON_DIAGNOSTIC_NOTICE in data["notice"]


def test_api_upload_strips_pii_and_reports_sanitization(api_client):
    """Verify POST /api/analyse-upload strips PII columns and returns privacy notice."""
    csv_content = (
        "employee_id,name,email,salary,work_hours_per_week,overtime_hours,meetings_per_day,deadlines_missed,experience_years,job_role,work_mode\n"
        "EMP001,John Doe,john@work.com,95000,42,4,3,1,4,Software Engineer,Remote\n"
        "EMP002,Jane Roe,jane@work.com,98000,50,8,5,2,6,Devops,Hybrid\n"
    )
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "employee_test_pii.csv")
    }

    resp = api_client.post("/api/analyse-upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    res_json = json.loads(resp.data)

    # PII fields stripped
    assert "stripped_pii_fields" in res_json
    assert "name" in res_json["stripped_pii_fields"]
    assert "email" in res_json["stripped_pii_fields"]
    assert "salary" in res_json["stripped_pii_fields"]
    assert "privacy_notice" in res_json
    assert "responsible_use_advisory" in res_json


def test_api_search_employee_returns_masked_id(api_client, dashboard_state: DashboardState):
    """Verify employee search returns masked ID and safeguards without exposing unneeded PII."""
    emp = dashboard_state.df.iloc[0]
    eid = str(emp["employee_id"])

    resp = api_client.get(f"/api/search-employee?id={eid}")
    assert resp.status_code == 200
    data = json.loads(resp.data)

    assert "masked_id" in data
    assert "***" in data["masked_id"]
    assert "workplace_indicators" in data
    assert "suggested_actions" in data
    assert data["is_medical_diagnosis"] is False


# ─── 6. PILOT READINESS DOCUMENTATION VERIFICATION ───────────────────────────

def test_pilot_readiness_specification_completeness():
    """Verify PILOT_READINESS.md exists and covers all required governance sections."""
    doc_path = Path("PILOT_READINESS.md").resolve()
    assert doc_path.exists(), "PILOT_READINESS.md must exist at repo root."

    text = doc_path.read_text(encoding="utf-8")
    required_sections = [
        "Executive Summary",
        "Intended Users",
        "Prohibited Use Cases",
        "Data Requirements",
        "Pre-Pilot Verification",
        "Employee Privacy, Access Control",
        "Key Performance Indicators",
        "Pilot Off-Ramping & Kill-Switch",
    ]
    for sec in required_sections:
        assert sec in text, f"Missing required pilot section: '{sec}'"
