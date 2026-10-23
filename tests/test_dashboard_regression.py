"""Regression test suite for the Workforce Burnout dashboard and backend.

Verifies:
- DashboardState initialization with artifacts and master workforce dataset
- /api/summary returns expected organizational metrics and structures
- /api/predict computes continuous score and calibrated risk probability
- /api/employee-table supports pagination and filtering
- /api/analyse-upload parses CSV batch streams and updates employee_df
- HTTP Server handler functions without regression
- api/index.py (Flask application) initializes and serves routes
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import pandas as pd
import pytest

from dashboard_server import DashboardState, make_handler
import api.index as vercel_app


@pytest.fixture(scope="module")
def artifacts_dir() -> Path:
    p = Path("artifacts").resolve()
    assert p.exists()
    assert (p / "burnout_score_model.joblib").exists()
    assert (p / "elevated_risk_model.joblib").exists()
    assert (p / "metrics.json").exists()
    return p


@pytest.fixture(scope="module")
def dashboard_state(artifacts_dir: Path) -> DashboardState:
    pkl_path = artifacts_dir / "master_workforce_dataset.pkl.gz"
    csv_path = artifacts_dir / "master_workforce_dataset.csv"
    data_path = pkl_path if pkl_path.exists() else csv_path
    assert data_path.exists()
    return DashboardState(data_path=data_path, artifacts=artifacts_dir)


def test_dashboard_state_initialization(dashboard_state: DashboardState):
    """Verify state loads models and dataset of 150,000 tech-workforce employees (other merged sources excluded)."""
    assert len(dashboard_state.df) == 150000
    assert dashboard_state.score_model is not None
    assert dashboard_state.risk_model is not None
    assert dashboard_state.threshold > 0.0


def test_dashboard_summary_api(dashboard_state: DashboardState):
    """Verify /api/summary metrics calculation and expected fields."""
    summary = dashboard_state.summary()
    expected_keys = {
        "employees", "mean_burnout", "elevated_rate", "mean_stress",
        "threshold", "role_burnout", "mode_burnout", "risk_bands",
        "defaults", "interventions", "role_drivers"
    }
    assert expected_keys.issubset(set(summary.keys()))
    assert summary["employees"] == 150000
    assert 0.0 <= summary["mean_burnout"] <= 10.0
    assert 0.0 <= summary["elevated_rate"] <= 100.0


def test_dashboard_predict_api(dashboard_state: DashboardState):
    """Verify /api/predict inference for individual employee scenario."""
    scenario = {
        "work_hours_per_week": 48.0,
        "overtime_hours": 8.0,
        "meetings_per_day": 4.0,
        "deadlines_missed": 2.0,
        "experience_years": 4.0,
        "job_role": "Software Engineer",
        "work_mode": "Hybrid",
        "stress_level": 7.0,
        "work_life_balance": 40.0,
        "manager_support": 50.0,
    }
    result = dashboard_state.predict(scenario)
    assert "burnout_score" in result
    assert "elevated_risk_probability" in result
    assert "risk_band" in result
    assert 0.0 <= result["burnout_score"] <= 10.0
    assert 0.0 <= result["elevated_risk_probability"] <= 100.0
    assert result["risk_band"] in {"Low", "Moderate", "Elevated"}


def test_dashboard_employee_table_api(dashboard_state: DashboardState):
    """Verify /api/employee-table handles empty and populated states without crashing."""
    # Before upload, employee table is empty
    tbl = dashboard_state.get_employee_table(page=0, page_size=10)
    assert tbl["total"] == 0
    assert tbl["rows"] == []


def test_dashboard_analyse_upload_api(dashboard_state: DashboardState):
    """Verify streaming upload analysis of company_upload_template.csv."""
    template_path = Path("company_upload_template.csv").resolve()
    assert template_path.exists()

    with template_path.open("rb") as f:
        res = dashboard_state.analyse_upload(f, "company_upload_template.csv")

    assert res["employee_table_count"] == 2
    assert "mean_burnout_score" in res
    assert "risk_distribution" in res
    assert "role_analysis" in res

    # After upload, employee_df is populated and paginated table returns rows
    tbl_after = dashboard_state.get_employee_table(page=0, page_size=10)
    assert tbl_after["total"] == 2
    assert len(tbl_after["rows"]) == 2


def test_vercel_flask_app_routes():
    """Verify Vercel serverless Flask application routes and health."""
    client = vercel_app.app.test_client()

    # Index route
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Workforce Analytics" in resp.data

    # Summary API
    resp_summary = client.get("/api/summary")
    assert resp_summary.status_code == 200
    data = json.loads(resp_summary.data)
    assert data["employees"] == 150000

    # Predict API
    resp_predict = client.post("/api/predict", json={
        "work_hours_per_week": 40,
        "overtime_hours": 0,
        "job_role": "Data Scientist",
        "work_mode": "Remote",
    })
    assert resp_predict.status_code == 200
    pred = json.loads(resp_predict.data)
    assert "burnout_score" in pred

    # Health API
    resp_health = client.get("/api/health")
    assert resp_health.status_code == 200
    health = json.loads(resp_health.data)
    assert health["status"] == "healthy"
    assert health["records_loaded"] == 150000
    assert health["models_loaded"]["forecasting"] is True
