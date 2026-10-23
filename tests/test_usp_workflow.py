"""Unit and integration tests for BurnoutIQ USP-first workflow.

Tests:
1. Time-series forecasting with empirical 95% prediction intervals and cohort filtering.
2. Verified intervention lifecycles and resolution of funnel discrepancies.
3. Intervention Command Center action records query, status updates, and disk persistence.
4. Logging new supportive interventions and recording subsequent follow-up assessment scores.
5. End-to-end link from baseline -> action -> follow-up observation -> measured change.
"""

import json
import pytest
from pathlib import Path
from api.index import app, get_state


@pytest.fixture(autouse=True)
def reset_state():
    """Ensure clean master state for each test."""
    state = get_state()
    state.reset_to_master()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_forecast_empirical_prediction_intervals_and_cohort_filter(client):
    """Verify forecast returns empirical 95% interval, standard error, and cohort filter."""
    res = client.get("/api/forecast")
    assert res.status_code == 200
    data = res.get_json()

    assert data.get("available") is True
    proj = data.get("next_projection", {})
    assert "standard_error_se" in proj
    assert "empirical_95_margin" in proj
    assert "interval_95_lower" in proj
    assert "interval_95_upper" in proj
    assert proj["interval_95_lower"] <= proj["projected_mean_cbi"] <= proj["interval_95_upper"]
    assert abs(proj["empirical_95_margin"] - 1.96 * proj["standard_error_se"]) < 0.05
    assert "95% range" in proj["interval_explanation"] and "covering" in proj["interval_explanation"]

    # Intervention markers are computed from the interventions file (busiest month, randomised pilot)
    waves = data.get("intervention_waves", [])
    assert len(waves) >= 2
    pilot = next(w for w in waves if w["label"] == "Randomised pilot")
    assert pilot["period"] == "2025-03"   # the pilot was randomised after the March assessment

    # Cohort filtering
    cohort_res = client.get("/api/forecast?cohort=Engineering")
    assert cohort_res.status_code == 200
    cdata = cohort_res.get_json()
    assert cdata["active_cohort"] == "Engineering"
    assert len(cdata["monthly_points"]) > 0


def test_interventions_dual_track_lifecycles(client):
    """Verify dual-track execution and reassessment lifecycles with explicit denominators."""
    res = client.get("/api/interventions-tracking")
    assert res.status_code == 200
    data = res.get_json()

    assert data.get("available") is True
    assert data.get("total_interventions") >= 1046

    # Operational execution track
    exec_life = data.get("execution_lifecycle", {})
    assert exec_life.get("active_assignments") >= 927
    assert exec_life.get("completed") >= 451
    assert exec_life.get("waitlist_control") == 119
    assert exec_life.get("in_progress") >= 90
    assert exec_life.get("declined_or_discontinued") == 319

    # Reassessment track
    reassess_life = data.get("reassessment_lifecycle", {})
    assert reassess_life.get("scheduled_cohort") >= 1046
    assert reassess_life.get("follow_up_completed") >= 574
    assert reassess_life.get("improving") > 0
    assert reassess_life.get("stable") > 0
    assert reassess_life.get("worsening") > 0
    assert reassess_life["improving"] + reassess_life["stable"] + reassess_life["worsening"] == reassess_life["follow_up_completed"]

    # Clarification notice
    note = data.get("funnel_clarification", "")
    assert f"({reassess_life['follow_up_completed']})" in note and f"({exec_life['completed']})" in note


def test_intervention_records_pagination_and_filters(client):
    """Verify /api/interventions/records returns paginated action queue and status filters."""
    res = client.get("/api/interventions/records?page=0&page_size=10")
    assert res.status_code == 200
    data = res.get_json()

    assert len(data.get("records", [])) == 10
    assert data.get("total_count") >= 1046
    assert "status_counts" in data
    assert data["status_counts"]["completed"] >= 450
    assert len(data.get("departments", [])) > 0

    # Filter by status
    comp_res = client.get("/api/interventions/records?status=completed&page_size=5")
    assert comp_res.status_code == 200
    cdata = comp_res.get_json()
    for rec in cdata["records"]:
        assert rec["action_status"] == "completed"

    # Search by employee ID
    search_res = client.get("/api/interventions/records?search=SYN-00017")
    assert search_res.status_code == 200
    sdata = search_res.get_json()
    assert len(sdata["records"]) >= 1
    assert sdata["records"][0]["employee_id"] == "SYN-00017"


def test_update_intervention_status_and_persistence(client):
    """Verify updating action status persists changes to disk."""
    res = client.get("/api/interventions/records?status=proposed&page_size=1")
    assert res.status_code == 200
    records = res.get_json().get("records", [])
    if not records:
        records = client.get("/api/interventions/records?page_size=1").get_json()["records"]

    target_id = records[0]["action_id"]
    orig_status = records[0]["action_status"]
    orig_owner = records[0].get("responsible_owner", "")
    orig_notes = records[0].get("notes", "")

    try:
        update_payload = {
            "action_id": target_id,
            "status": "in_progress",
            "owner": "Test Lead Ops",
            "notes": "Verified by automated test suite",
        }
        post_res = client.post("/api/interventions/update-status", json=update_payload)
        assert post_res.status_code == 200
        updated = post_res.get_json().get("record", {})
        assert updated["action_status"] == "in_progress"
        assert updated["responsible_owner"] == "Test Lead Ops"
        assert "Verified by automated test suite" in updated["notes"]

        # Verify query returns updated state
        verify_res = client.get(f"/api/interventions/records?search={target_id}")
        assert verify_res.status_code == 200
        v_records = verify_res.get_json()["records"]
        assert any(r["action_id"] == target_id and r["action_status"] == "in_progress" for r in v_records)
    finally:
        # Revert state back
        client.post("/api/interventions/update-status", json={
            "action_id": target_id,
            "status": orig_status,
            "owner": orig_owner,
            "notes": orig_notes,
        })


def test_record_new_intervention_and_followup_assessment(client):
    """Verify recording a new intervention and then logging a subsequent follow-up assessment."""
    action_id = None
    try:
        # 1. Record new intervention
        new_payload = {
            "employee_id": "SYN-00099",
            "intervention_type": "workload_review",
            "owner": "Automated Unit Test Partner",
            "follow_up_due_date": "2026-06-30",
            "notes": "Created in unit test",
        }
        create_res = client.post("/api/interventions/record", json=new_payload)
        assert create_res.status_code == 200
        created = create_res.get_json().get("record", {})
        assert created["employee_id"] == "SYN-00099"
        assert created["action_id"].startswith("INT-")
        action_id = created["action_id"]
        base_score = created["baseline_cbi_score"]

        # 2. Record subsequent assessment showing improvement (score lowered by 15 points)
        follow_up_score = max(0.0, base_score - 15.0)
        followup_payload = {
            "action_id": action_id,
            "follow_up_cbi_score": follow_up_score,
            "assessment_date": "2026-06-25",
            "notes": "Follow-up test assessment recorded",
        }
        follow_res = client.post("/api/interventions/record-followup", json=followup_payload)
        assert follow_res.status_code == 200
        f_record = follow_res.get_json().get("record", {})
        assert f_record["follow_up_cbi_score"] == round(follow_up_score, 1)
        assert f_record["observed_change"] <= -5.0
        assert f_record["outcome_status"] == "improving"
    finally:
        if action_id:
            state = get_state()
            state.longitudinal_tracker.action_records = [
                r for r in state.longitudinal_tracker.action_records
                if r["action_id"] != action_id
            ]
            state.longitudinal_tracker.save_action_records()
