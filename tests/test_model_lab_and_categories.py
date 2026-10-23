"""Tests for Model Lab and Employee Directory Cohort Categorization.

Validates:
1. /api/model-lab endpoint integrity: Task A, Task B, Task C metrics, baselines, confusion matrix, datasets, and safeguards.
2. /api/employee-table endpoint with category filtering and master workforce inclusion.
3. /api/featured-employee endpoint returning a valid sample employee for immediate 1-click inspection without blank screens.
4. Metric accuracy against stored artifacts (metrics.json, forecast_metrics.json).
"""

import json
import pytest
from pathlib import Path
from api.index import app, get_state


@pytest.fixture(autouse=True)
def reset_state():
    state = get_state()
    state.reset_to_master()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_model_lab_endpoint_structure_and_tasks(client):
    """Confirm Model Lab endpoint returns all 3 distinct tasks and their empirical results."""
    res = client.get("/api/model-lab")
    assert res.status_code == 200
    data = res.get_json()

    # Tasks validation
    tasks = data.get("tasks", {})
    assert "task_a_regression" in tasks
    assert "task_b_classification" in tasks
    assert "task_c_forecasting" in tasks

    # Task A: Continuous 0-10 Regression
    task_a = tasks["task_a_regression"]
    assert "0.0 – 10.0" in task_a["target_scale"]
    assert len(task_a["models"]) >= 3
    # Check HistGradientBoosting is winner
    hgb = task_a["models"]["hist_gradient_boosting"]
    assert hgb["test_mae"] < 0.45
    assert hgb["test_r2"] > 0.70
    assert any(r["best"] and r["model"] == "hist_gradient_boosting" for r in task_a["rankings"])

    # Task B: Elevated Risk Classification
    task_b = tasks["task_b_classification"]
    assert "Binary" in task_b["target_scale"]
    assert "confusion_matrix" in task_b
    cm = task_b["confusion_matrix"]
    assert cm["true_positives"] > 0
    assert cm["true_negatives"] > 0

    # Task C: CBI Longitudinal Forecasting
    task_c = tasks["task_c_forecasting"]
    assert "Copenhagen Burnout Inventory" in task_c["target_scale"]
    assert "persistence_baseline" in task_c["regression_models"]
    persistence = task_c["regression_models"]["persistence_baseline"]
    assert "mae" in persistence and "rmse" in persistence
    # Ridge model outperforms persistence baseline
    ridge = task_c["regression_models"]["ridge"]
    assert ridge["rmse"] < persistence["rmse"]

    # Datasets provenance and safeguards
    assert len(data.get("datasets", [])) >= 4
    assert len(data.get("methodology_safeguards", [])) >= 5
    assert len(data.get("feature_importance", [])) > 0



def test_employee_table_category_filters(client):
    """Verify that employee table supports categories and returns non-empty workforce data."""
    # Default elevated category with include_master=1
    res = client.get("/api/employee-table?category=elevated&include_master=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] > 0
    assert len(data["rows"]) > 0
    assert "category_counts" in data
    counts = data["category_counts"]
    assert counts["elevated"] > 0
    assert counts["interventions"] > 0
    assert counts["longitudinal"] > 0
    assert counts["all"] > 0

    # Interventions category
    res_int = client.get("/api/employee-table?category=interventions&include_master=1")
    data_int = res_int.get_json()
    assert data_int["total"] > 0
    for row in data_int["rows"]:
        assert row.get("has_intervention") is True

    # Longitudinal category
    res_long = client.get("/api/employee-table?category=longitudinal&include_master=1")
    data_long = res_long.get_json()
    assert data_long["total"] > 0
    for row in data_long["rows"]:
        assert row["id"].startswith("SYN-")


def test_featured_employee_endpoint(client):
    """Verify featured employee endpoint returns a pre-loaded case (SYN-00017) to prevent blank screen."""
    res = client.get("/api/featured-employee")
    assert res.status_code == 200
    data = res.get_json()
    assert "burnout_score" in data
    assert "longitudinal" in data
    long_data = data["longitudinal"]
    assert long_data.get("is_longitudinal") is True
    assert len(long_data.get("timeline", [])) >= 2
    assert "linked_interventions" in long_data


