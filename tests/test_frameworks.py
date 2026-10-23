"""Tests for the single BurnoutIQ framework: the monitoring loop.

Validates:
1. /api/frameworks describes one framework (inner loop of 5 stages + quarterly learning loop).
2. /api/loop returns values computed by the burnoutiq package, consistent with each other.
3. The old framework images are no longer served.
"""

import pytest
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


def test_single_loop_framework(client):
    data = client.get("/api/frameworks").get_json()
    assert data["frameworks_count"] == 1
    fw = data["framework"]
    assert [s["id"] for s in fw["inner_loop"]] == ["assess", "predict", "simulate", "intervene", "verify"]
    assert [s["id"] for s in fw["outer_loop"]] == ["learn"]


def test_loop_payload_is_computed_and_consistent(client):
    res = client.get("/api/loop")
    assert res.status_code == 200
    d = res.get_json()
    assert d["available"] and d["period"] == "2025-12"
    comp, imp = d["company"], d["impact"]
    assert sum(comp["status"].values()) == comp["employees_with_record"]
    assert imp["outcomes"]["improved"] + imp["outcomes"]["no_change"] + imp["outcomes"]["worsened"] == imp["follow_up"]["followed_up"]
    assert d["forecast_metrics"]["beats_persistence"]
    assert all(e["evidence"] for e in d["effects"])
    for key in ("worsening", "how_much", "why", "evidence"):
        assert d["brief"][key]["value"]


def test_loop_payload_for_earlier_month(client):
    d = client.get("/api/loop?period=2025-06").get_json()
    assert d["period"] == "2025-06"
    assert d["impact"]["follow_up"]["due"] <= client.get("/api/loop").get_json()["impact"]["follow_up"]["due"]


def test_old_framework_images_not_served(client):
    assert client.get("/frameworks/01_burnout_prevention_leverage.jpg").status_code == 404
