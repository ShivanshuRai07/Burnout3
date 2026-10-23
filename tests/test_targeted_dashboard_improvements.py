"""Tests for Targeted Dashboard Improvements (Phase 5).

Verifies:
1. Live Forecasting endpoint (/api/forecast) and model benchmarks.
2. AI Interventions tracking endpoint (/api/interventions-tracking) and outcome classification.
3. Summary endpoint with active dataset badges and historical trends.
4. Pseudonymous employee search with longitudinal history vs single-snapshot notices.
5. Data-driven CSV upload workflow, active dataset switching, and upload failure rollback.
"""

import io
import json
import pytest
from pathlib import Path

from api.index import app, get_state

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def reset_state_to_master():
    """Ensure each test starts with the clean Tech Workforce Dataset."""
    state = get_state()
    state.reset_to_master()
    yield
    state.reset_to_master()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_forecast_endpoint_structure_and_metrics(client):
    """Verify /api/forecast returns complete time series projection and zero-leakage metrics."""
    res = client.get("/api/forecast")
    assert res.status_code == 200
    data = res.get_json()

    assert data.get("available") is True
    assert "CBI" in data.get("scale", "")
    assert "active_dataset" in data
    assert data["active_dataset"]["is_upload"] is False

    # Check monthly points
    monthly = data.get("monthly_points", [])
    assert len(monthly) >= 10
    first_pt = monthly[0]
    assert "period" in first_pt
    assert "actual_observed_t" in first_pt
    assert "forecast_predicted_t1" in first_pt
    assert "persistence_baseline_t1" in first_pt

    # Check next period projection
    proj = data.get("next_projection", {})
    assert proj.get("horizon") == "1 Month Ahead (t+1)"
    assert proj.get("forecast_period") == "2026-01"
    assert proj.get("last_observed_date") == "2025-12-27"
    assert proj.get("projected_mean_cbi") > 0
    assert proj.get("uncertainty_rmse") > 0
    assert proj.get("uncertainty_lower_cbi") < proj.get("projected_mean_cbi") < proj.get("uncertainty_upper_cbi")

    # Check zero-leakage benchmarks
    benchmarks = data.get("benchmarks", {})
    assert "ridge" in benchmarks
    assert "persistence_baseline" in benchmarks
    assert benchmarks["ridge"]["mae"] < benchmarks["persistence_baseline"]["mae"]
    assert benchmarks["ridge"]["rmse"] < benchmarks["persistence_baseline"]["rmse"]
    assert "no employee appears in both" in data.get("leakage_safeguard", "").lower()


def test_interventions_tracking_endpoint(client):
    """Verify /api/interventions-tracking returns completion funnel, outcome distributions, and disclaimer."""
    res = client.get("/api/interventions-tracking")
    assert res.status_code == 200
    data = res.get_json()

    assert data.get("available") is True
    assert data.get("total_interventions") == 1046
    assert 40.0 <= data.get("completion_rate", 0) <= 60.0
    # follow-up counts a survey in the intervention's end month or the month after (burnoutiq.intervene)
    rl = data["reassessment_lifecycle"]
    assert data["follow_up_coverage_rate"] == round(rl["follow_up_completed"] / rl["scheduled_cohort"] * 100, 1)
    assert 0 < data["follow_up_coverage_rate"] < 100

    # Funnel checks
    funnel = data.get("funnel", {})
    assert funnel.get("recommended") == 1046
    assert funnel.get("accepted_or_planned") > 0
    assert funnel.get("implemented_or_completed") > 0
    assert funnel.get("reassessed_followup") > 0
    assert funnel["recommended"] >= funnel["accepted_or_planned"] >= funnel["implemented_or_completed"]

    # Outcomes breakdown
    outcomes = data.get("outcome_by_type", {})
    assert len(outcomes) >= 4
    for itype, breakdown in outcomes.items():
        assert "improving" in breakdown
        assert "stable" in breakdown
        assert "worsening" in breakdown
        assert "insufficient_data" in breakdown
        assert breakdown["total"] > 0

    # Sample records
    samples = data.get("sample_records", [])
    assert len(samples) > 0
    sample = samples[0]
    assert "employee_id" in sample
    assert "intervention_type" in sample
    assert "outcome_status" in sample
    assert sample["outcome_status"] in {"improving", "stable", "worsening", "insufficient_data"}

    # Disclaimer check
    assert "causal" in data.get("non_causal_disclaimer", "").lower()


def test_summary_includes_active_dataset_and_longitudinal_trend(client):
    """Verify /api/summary includes active dataset info, historical trend, and intervention metrics."""
    res = client.get("/api/summary")
    assert res.status_code == 200
    data = res.get_json()

    assert "active_dataset" in data
    assert data["active_dataset"]["is_upload"] is False
    assert data["active_dataset"]["record_count"] == 150000

    assert "historical_trend" in data
    assert len(data["historical_trend"]) == 12
    for h in data["historical_trend"]:
        assert "period" in h
        assert "mean_cbi_score" in h
        assert "levels" in h

    assert "intervention_metrics" in data
    assert data["intervention_metrics"]["total_interventions"] == 1046
    assert data["intervention_metrics"]["completion_rate"] == 43.1
    assert data["intervention_metrics"]["follow_up_coverage_rate"] == 54.9


def test_employee_search_longitudinal_profile(client):
    """Verify longitudinal employee returns dated timeline, while cross-sectional returns snapshot notice."""
    # 1. Longitudinal employee from panel dataset
    res_long = client.get("/api/search-employee?id=SYN-00017")
    assert res_long.status_code == 200
    data_long = res_long.get_json()
    assert "longitudinal" in data_long
    long_info = data_long["longitudinal"]
    assert long_info.get("is_longitudinal") is True
    assert len(long_info.get("timeline", [])) == 12
    assert "cbi_work_score" in long_info["timeline"][0]
    assert len(long_info.get("linked_interventions", [])) >= 1

    # 2. Cross-sectional employee from master dataset
    res_cross = client.get("/api/search-employee?id=tech_0")
    assert res_cross.status_code == 200
    data_cross = res_cross.get_json()
    assert "longitudinal" in data_cross
    cross_info = data_cross["longitudinal"]
    assert cross_info.get("is_longitudinal") is False
    assert "single assessment snapshot" in cross_info.get("notice", "").lower()


def test_csv_upload_workflow_and_active_dataset_switching(client):
    """Verify uploading different cohorts updates active dataset, scores, and resets cleanly."""
    # 1. Upload high-workload tech cohort (100 rows)
    tech_path = DATA_DIR / "test_upload_tech_cohort.csv"
    with open(tech_path, "rb") as f:
        res_tech = client.post(
            "/api/analyse-upload",
            data={"file": (f, "test_upload_tech_cohort.csv")},
            content_type="multipart/form-data"
        )
    assert res_tech.status_code == 200
    data_tech = res_tech.get_json()

    assert data_tech.get("employee_table_count") == 100
    assert data_tech["active_dataset"]["is_upload"] is True
    assert data_tech["active_dataset"]["record_count"] == 100
    tech_mean = data_tech.get("mean_burnout_score")
    assert tech_mean > 3.0

    # Verify state reflects uploaded file
    state = get_state()
    assert state.active_dataset_info["is_upload"] is True
    assert state.active_dataset_info["record_count"] == 100

    # 2. Upload low-workload balanced cohort (50 rows)
    bal_path = DATA_DIR / "test_upload_balanced_cohort.csv"
    with open(bal_path, "rb") as f:
        res_bal = client.post(
            "/api/analyse-upload",
            data={"file": (f, "test_upload_balanced_cohort.csv")},
            content_type="multipart/form-data"
        )
    assert res_bal.status_code == 200
    data_bal = res_bal.get_json()

    assert data_bal.get("employee_table_count") == 50
    assert data_bal["active_dataset"]["is_upload"] is True
    assert data_bal["active_dataset"]["record_count"] == 50
    bal_mean = data_bal.get("mean_burnout_score")
    assert bal_mean < tech_mean  # Balanced cohort should have lower burnout

    # 3. Reset back to master workforce dataset
    res_reset = client.post("/api/reset-dataset")
    assert res_reset.status_code == 200
    reset_data = res_reset.get_json()
    assert reset_data["active_dataset"]["is_upload"] is False
    assert reset_data["active_dataset"]["record_count"] == 150000

    # Verify summary is also back to master
    sum_res = client.get("/api/summary")
    sum_data = sum_res.get_json()
    assert sum_data["active_dataset"]["is_upload"] is False
    assert sum_data["employees"] == 150000


def test_failed_upload_does_not_corrupt_active_dataset(client):
    """Verify that uploading an invalid file rejects gracefully and preserves existing valid dataset."""
    state = get_state()
    initial_dataset = dict(state.active_dataset_info)

    # Attempt uploading invalid non-CSV or empty
    res_bad = client.post(
        "/api/analyse-upload",
        data={"file": (io.BytesIO(b""), "bad_file.txt")},
        content_type="multipart/form-data"
    )
    assert res_bad.status_code == 400

    # Verify active dataset was NOT corrupted or overwritten
    assert state.active_dataset_info == initial_dataset
    assert state.active_dataset_info["is_upload"] is False
    assert state.active_dataset_info["record_count"] == 150000
