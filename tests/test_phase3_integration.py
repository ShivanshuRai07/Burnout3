"""Phase 3 Integration & Validation Test Suite for BurnoutIQ.

Verifies:
1. Model loading: regressor, calibrated classifier, and operational threshold artifacts
2. Prediction accuracy on known test cases (Low, Moderate, and Elevated risk profiles)
3. Input validation: type errors, negative bounds, max boundaries, NaN/inf, missing values
4. Categorical mapping: case insensitivity, synonyms, unknown categories
5. UI slider scale alignment: 1-10 range mapping to underlying model domain space
6. Non-diagnostic disclaimer notice in all prediction responses
7. API endpoints response formats and error handling (HTTP 200 and HTTP 400)
8. Backward compatibility and regression checks against all existing dashboard endpoints
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd
import joblib

from burnout_platform.validation import (
    validate_and_clean_payload,
    compute_prediction_result,
    NON_DIAGNOSTIC_NOTICE,
    EVALUATION_THRESHOLD,
    PROBABILITY_THRESHOLD,
    NUMERIC_BOUNDS,
    clean_categorical,
    ROLE_LOOKUP,
    WORK_MODE_LOOKUP,
)
from burnout_platform.features import engineer_features
from dashboard_server import DashboardState
import api.index as vercel_app


@pytest.fixture(scope="module")
def artifacts_dir() -> Path:
    p = Path("artifacts").resolve()
    assert p.exists()
    return p


@pytest.fixture(scope="module")
def score_model(artifacts_dir: Path):
    model_path = artifacts_dir / "burnout_score_model.joblib"
    assert model_path.exists(), f"Missing score model: {model_path}"
    return joblib.load(model_path)


@pytest.fixture(scope="module")
def risk_model(artifacts_dir: Path):
    model_path = artifacts_dir / "elevated_risk_model.joblib"
    assert model_path.exists(), f"Missing risk model: {model_path}"
    return joblib.load(model_path)


@pytest.fixture(scope="module")
def metrics_meta(artifacts_dir: Path) -> dict:
    meta_path = artifacts_dir / "metrics.json"
    assert meta_path.exists(), f"Missing metrics file: {meta_path}"
    return json.loads(meta_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dashboard_state(artifacts_dir: Path) -> DashboardState:
    pkl_path = artifacts_dir / "master_workforce_dataset.pkl.gz"
    csv_path = artifacts_dir / "master_workforce_dataset.csv"
    data_path = pkl_path if pkl_path.exists() else csv_path
    assert data_path.exists()
    return DashboardState(data_path=data_path, artifacts=artifacts_dir)


@pytest.fixture(scope="module")
def api_client():
    return vercel_app.app.test_client()


# ─── 1. MODEL LOADING & SCHEMAS ─────────────────────────────────────────────

def test_model_artifacts_loading(score_model, risk_model, metrics_meta):
    """Verify saved models load, are scikit-learn Pipelines, and match metrics metadata."""
    # Continuous Regressor
    assert hasattr(score_model, "named_steps"), "Score model must be a scikit-learn Pipeline."
    assert "preprocessor" in score_model.named_steps
    assert "model" in score_model.named_steps
    assert hasattr(score_model.named_steps["model"], "predict")

    # Calibrated Classifier
    assert hasattr(risk_model, "named_steps"), "Risk model must be a scikit-learn Pipeline."
    assert "preprocessor" in risk_model.named_steps
    assert "model" in risk_model.named_steps
    assert hasattr(risk_model.named_steps["model"], "predict_proba")

    # Threshold metadata
    assert metrics_meta["risk_model"]["threshold"] == EVALUATION_THRESHOLD
    assert metrics_meta["recommended_model"] == "hist_gradient_boosting"


def test_model_expected_features_schema(score_model):
    """Verify the pipeline expects the 17 measured columns and no hand-weighted composite indexes."""
    preproc = score_model.named_steps["preprocessor"]
    expected_features = set(preproc.feature_names_in_)
    assert "work_hours_per_week" in expected_features
    assert "job_role" in expected_features
    assert "work_mode" in expected_features
    assert not expected_features & {"workload_index", "wellness_score", "support_index", "meeting_load"}
    assert len(expected_features) == 17


# ─── 2. PREDICTION ACCURACY ON KNOWN TEST CASES ──────────────────────────────

def test_known_low_risk_scenario(dashboard_state: DashboardState):
    """Verify healthy, low-workload scenario predicts low burnout score and band."""
    scenario = {
        "work_hours_per_week": 35.0,
        "overtime_hours": 0.0,
        "meetings_per_day": 1.0,
        "deadlines_missed": 0.0,
        "stress_level": 1.5,
        "work_life_balance": 9.0,   # UI slider 1-10 -> maps to 180 (high wellness)
        "manager_support": 9.0,     # UI slider 1-10 -> maps to 180 (high support)
        "job_satisfaction": 9.0,    # UI slider 1-10 -> maps to 180 (high satisfaction)
        "sleep_hours": 8.5,
        "physical_activity_days": 4.0,
        "job_role": "Software Engineer",
        "work_mode": "Remote",
    }
    result = dashboard_state.predict(scenario)

    assert result["burnout_score"] < 2.50, f"Expected < 2.50, got {result['burnout_score']}"
    assert result["risk_band"] == "Low"
    assert result["elevated_risk_probability"] < PROBABILITY_THRESHOLD
    assert result["is_elevated_risk"] is False
    assert result["is_medical_diagnosis"] is False
    assert NON_DIAGNOSTIC_NOTICE in result["notice"]


def test_known_elevated_risk_scenario(dashboard_state: DashboardState):
    """Verify heavy workload, high overtime, high stress scenario predicts elevated risk."""
    scenario = {
        "work_hours_per_week": 65.0,
        "overtime_hours": 18.0,
        "meetings_per_day": 8.0,
        "deadlines_missed": 4.0,
        "stress_level": 9.5,
        "work_life_balance": 2.0,   # UI slider 1-10 -> maps to 40 (poor balance)
        "manager_support": 1.5,     # UI slider 1-10 -> maps to 30 (poor support)
        "job_satisfaction": 2.0,    # UI slider 1-10 -> maps to 40 (low satisfaction)
        "sleep_hours": 4.5,
        "physical_activity_days": 0.0,
        "job_role": "Software Engineer",
        "work_mode": "Onsite",
    }
    result = dashboard_state.predict(scenario)

    assert result["burnout_score"] >= EVALUATION_THRESHOLD, f"Expected >= {EVALUATION_THRESHOLD}, got {result['burnout_score']}"
    assert result["risk_band"] == "Elevated"
    assert result["elevated_risk_probability"] >= 50.0
    assert result["is_elevated_risk"] is True
    assert result["is_medical_diagnosis"] is False


def test_known_moderate_risk_scenario(dashboard_state: DashboardState):
    """Verify moderate workload profile predicts moderate risk band (2.50 to 3.70)."""
    scenario = {
        "work_hours_per_week": 48.0,
        "overtime_hours": 6.0,
        "meetings_per_day": 4.0,
        "deadlines_missed": 2.0,
        "stress_level": 6.5,
        "work_life_balance": 4.0,   # UI slider 1-10 -> maps to 80 (below median)
        "manager_support": 4.0,     # UI slider 1-10 -> maps to 80 (below median)
        "job_satisfaction": 4.0,
        "sleep_hours": 6.0,
        "job_role": "Software Engineer",
        "work_mode": "Hybrid",
    }
    result = dashboard_state.predict(scenario)

    assert 2.50 <= result["burnout_score"] < EVALUATION_THRESHOLD, (
        f"Expected between 2.50 and {EVALUATION_THRESHOLD}, got {result['burnout_score']}"
    )
    assert result["risk_band"] == "Moderate"


# ─── 3. INPUT VALIDATION & MISSING VALUES ───────────────────────────────────

def test_empty_payload_uses_defaults(dashboard_state: DashboardState):
    """Verify empty payload safely predicts using master dataset defaults."""
    result = dashboard_state.predict({})
    assert "burnout_score" in result
    assert "elevated_risk_probability" in result
    assert result["risk_band"] in {"Low", "Moderate", "Elevated"}


def test_invalid_payload_type():
    """Verify non-dictionary input raises ValueError."""
    with pytest.raises(ValueError, match="JSON object"):
        validate_and_clean_payload(["not", "a", "dict"], {})


def test_invalid_numeric_string():
    """Verify unparseable string raises descriptive ValueError."""
    with pytest.raises(ValueError, match="must be a valid number"):
        validate_and_clean_payload({"work_hours_per_week": "forty-five"}, {})


def test_nan_or_inf_numeric():
    """Verify NaN and Inf values are rejected safely."""
    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        validate_and_clean_payload({"work_hours_per_week": float("nan")}, {})

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        validate_and_clean_payload({"stress_level": float("inf")}, {})


def test_negative_numeric_bounds():
    """Verify negative bounds are rejected for non-negative features."""
    with pytest.raises(ValueError, match="cannot be less than 0.0"):
        validate_and_clean_payload({"work_hours_per_week": -10.0}, {})

    with pytest.raises(ValueError, match="cannot be less than 0.0"):
        validate_and_clean_payload({"stress_level": -1.0}, {})

    with pytest.raises(ValueError, match="cannot be less than 0.0"):
        validate_and_clean_payload({"sleep_hours": -0.5}, {})


def test_maximum_numeric_bounds():
    """Verify excessive bounds beyond physical/domain reality are rejected."""
    with pytest.raises(ValueError, match="cannot exceed maximum limit of 168.0"):
        validate_and_clean_payload({"work_hours_per_week": 200.0}, {})

    with pytest.raises(ValueError, match="cannot exceed maximum limit of 10.0"):
        validate_and_clean_payload({"stress_level": 11.5}, {})

    with pytest.raises(ValueError, match="cannot exceed maximum limit of 24.0"):
        validate_and_clean_payload({"sleep_hours": 25.0}, {})


def test_slider_scale_mapping():
    """Verify 1-10 slider inputs are mapped to 20-200 domain space, and raw values >10 preserved."""
    # 5.0 on slider (midpoint) maps to 100.0
    cleaned = validate_and_clean_payload({"work_life_balance": 5.0, "manager_support": 5.0}, {})
    assert cleaned["work_life_balance"] == 100.0
    assert cleaned["manager_support"] == 100.0

    # Direct model domain input (>10) is preserved as-is
    cleaned_direct = validate_and_clean_payload({"work_life_balance": 120.0, "manager_support": 110.0}, {})
    assert cleaned_direct["work_life_balance"] == 120.0
    assert cleaned_direct["manager_support"] == 110.0


def test_categorical_normalization():
    """Verify casing, whitespace, and synonym mapping for categoricals."""
    # Lowercase & surrounding whitespace
    cleaned = validate_and_clean_payload({
        "job_role": "  software engineer  ",
        "work_mode": "remote",
        "company_size": "startup",
    }, {})
    assert cleaned["job_role"] == "Software Engineer"
    assert cleaned["work_mode"] == "Remote"
    assert cleaned["company_size"] == "Startup"

    # Synonyms
    cleaned_syn = validate_and_clean_payload({
        "job_role": "devops engineer",
        "work_mode": "wfh",
        "company_size": "midsize",
    }, {})
    assert cleaned_syn["job_role"] == "Devops"
    assert cleaned_syn["work_mode"] == "Remote"
    assert cleaned_syn["company_size"] == "Mid-size"

    # Unknown category safely title-cased and handled by OneHotEncoder
    cleaned_unknown = validate_and_clean_payload({
        "job_role": "Research Scientist",
        "work_mode": "Hybrid",
    }, {})
    assert cleaned_unknown["job_role"] == "Research Scientist"


# ─── 4. API RESPONSES & MEDICAL DISCLAIMER ──────────────────────────────────

def test_api_predict_success(api_client):
    """Verify POST /api/predict returns 200 with all required fields and notice."""
    resp = api_client.post("/api/predict", json={
        "work_hours_per_week": 42,
        "overtime_hours": 4,
        "stress_level": 5.5,
        "job_role": "Data Scientist",
        "work_mode": "Hybrid",
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)

    assert "burnout_score" in data
    assert "elevated_risk_probability" in data
    assert "risk_band" in data
    assert "threshold" in data
    assert "probability_threshold" in data
    assert "is_elevated_risk" in data
    assert "is_medical_diagnosis" in data
    assert data["is_medical_diagnosis"] is False
    assert "notice" in data
    assert "not a medical diagnosis" in data["notice"]


def test_api_predict_invalid_input_returns_400(api_client):
    """Verify invalid inputs return HTTP 400 Bad Request with JSON error message."""
    # Negative work hours
    resp_neg = api_client.post("/api/predict", json={"work_hours_per_week": -5})
    assert resp_neg.status_code == 400
    data_neg = json.loads(resp_neg.data)
    assert "error" in data_neg
    assert "cannot be less than 0.0" in data_neg["error"]

    # Non-numeric string
    resp_str = api_client.post("/api/predict", json={"stress_level": "extreme"})
    assert resp_str.status_code == 400
    data_str = json.loads(resp_str.data)
    assert "error" in data_str
    assert "must be a valid number" in data_str["error"]


# ─── 5. EXISTING DASHBOARD REGRESSION CHECKS ────────────────────────────────

def test_regression_summary_endpoint(api_client):
    """Verify /api/summary structure is completely intact."""
    resp = api_client.get("/api/summary")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    for key in ["employees", "mean_burnout", "elevated_rate", "role_burnout", "mode_burnout", "risk_bands"]:
        assert key in data


def test_regression_search_employee_endpoint(api_client, dashboard_state: DashboardState):
    """Verify /api/search-employee returns employee profile with validated models."""
    first_emp = dashboard_state.df.iloc[0]
    emp_id = str(first_emp["employee_id"])

    resp = api_client.get(f"/api/search-employee?id={emp_id}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "burnout_score" in data
    assert "elevated_risk_probability" in data
    assert "risk_band" in data
    assert "notice" in data


def test_regression_employee_table_endpoint(api_client):
    """Verify /api/employee-table handles pagination."""
    resp = api_client.get("/api/employee-table?page=0&page_size=10")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "total" in data
    assert "rows" in data
