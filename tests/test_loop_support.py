"""Intervene from the person page: log support, update its status, and let the next month verify it."""
import pytest

from api.index import app, get_state


@pytest.fixture(autouse=True)
def reset_state():
    get_state().reset_to_master()
    yield
    get_state().reset_to_master()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def log(client, **kw):
    body = {"employee_id": "SYN-00339", "intervention_type": "workload_review", "owner": "Priya (HR)",
            "start_date": "2025-12-01", "planned_end_date": "2025-12-31", "notes": "rebalance sprint load", **kw}
    return client.post("/api/loop/support", json=body)


def test_logged_support_is_verified_when_the_next_month_arrives(client):
    client.post("/api/loop/demo-start", json={})
    res = log(client)
    assert res.status_code == 200, res.get_json()
    sid = res.get_json()["support"]["intervention_id"]
    assert sid.startswith("LOG-")

    prof = client.get("/api/search-employee?id=SYN-00339").get_json()["longitudinal"]
    mine = next(r for r in prof["linked_interventions"] if r["action_id"] == sid)
    assert mine["responsible_owner"] == "Priya (HR)" and mine["logged_here"]
    assert mine["outcome_status"] == "insufficient_data"

    assert client.post("/api/loop/support/status", json={"intervention_id": sid, "status": "completed"}).status_code == 200
    assert client.post("/api/loop/demo-next").status_code == 200       # December arrives
    prof = client.get("/api/search-employee?id=SYN-00339").get_json()["longitudinal"]
    mine = next(r for r in prof["linked_interventions"] if r["action_id"] == sid)
    assert mine["action_status"] == "completed"
    assert mine["baseline_cbi_score"] is not None and mine["follow_up_cbi_score"] is not None
    assert mine["outcome_status"] in ("improving", "stable", "worsening")


def test_invalid_support_is_refused(client):
    assert log(client, employee_id="SYN-99999").status_code == 400
    assert log(client, intervention_type="magic").status_code == 400
    assert log(client, owner="").status_code == 400
    assert "end date" in log(client, start_date="2026-02-01").get_json()["error"]
    bad = client.post("/api/loop/support/status", json={"intervention_id": "LOG-9999", "status": "completed"})
    assert bad.status_code == 400


def test_support_types_listed_with_evidence(client):
    types = client.get("/api/loop").get_json()["support_types"]
    assert [t["type"] for t in types] == ["workload_review", "schedule_adjustment", "eap_counselling", "wellbeing_workshop"]
    assert all(t["evidence"] for t in types)


def test_quick_tab_status_lists(client):
    d = client.get("/api/loop/employees?status=follow_up_due,follow_up_overdue&page_size=50").get_json()
    assert d["total"] > 0 and {r["status"] for r in d["rows"]} <= {"follow_up_due", "follow_up_overdue"}
