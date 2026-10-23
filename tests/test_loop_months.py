"""Month-by-month operation: live demo, adding a month, predicted vs actual, and the ranked employee list."""
import io
from pathlib import Path

import pandas as pd
import pytest

from api.index import app, get_state

DATA = Path(__file__).resolve().parent.parent / "Datasets" / "burnoutiq_dataset" / "data"


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


def csv(df):
    return (io.BytesIO(df.to_csv(index=False).encode()), "f.csv")


def test_live_demo_adds_a_month_and_checks_the_forecast(client):
    res = client.post("/api/loop/demo-start", json={})
    assert res.status_code == 200
    assert res.get_json()["source"]["next_period"] == "2025-12"
    first = client.get("/api/loop").get_json()
    assert first["period"] == "2025-11" and first["check"] is None
    assert first["periods"][-1] == "2025-11"

    res = client.post("/api/loop/demo-next")
    assert res.status_code == 200 and res.get_json()["source"]["months_added"] == 1
    d = client.get("/api/loop").get_json()
    assert d["period"] == "2025-12"
    c = d["check"]
    assert c["n"] > 100 and 85 <= c["inside_range_pct"] <= 100 and c["mae"] > 0

    # no more months in the demo; earlier months stay viewable
    assert client.post("/api/loop/demo-next").status_code == 400
    assert client.get("/api/loop?period=2025-06").get_json()["period"] == "2025-06"


def test_demo_statuses_use_only_what_was_known_then(client):
    client.post("/api/loop/demo-start", json={"until": "2025-04"})
    iv = get_state().longitudinal_tracker.loop.inputs.interventions
    assert (iv["referral_period"] <= "2025-04").all()
    ended_later = pd.to_datetime(iv["planned_end_date"], errors="coerce").dt.strftime("%Y-%m") > "2025-04"
    assert not iv.loc[ended_later, "completion_status"].isin(["completed", "not_completed"]).any()


def test_add_month_to_uploaded_company(client):
    emp = pd.read_csv(DATA / "employees.csv").head(200)
    mon = pd.read_csv(DATA / "assessments.csv")
    mon = mon[mon["employee_id"].isin(set(emp["employee_id"]))]
    upload = {"employees": csv(emp), "monthly": csv(mon[mon["period"] <= "2025-10"])}
    assert client.post("/api/loop/upload", data=upload, content_type="multipart/form-data").status_code == 200

    res = client.post("/api/loop/add-month", data={"monthly": csv(mon[mon["period"] == "2025-11"])},
                      content_type="multipart/form-data")
    assert res.status_code == 200, res.get_json()
    d = client.get("/api/loop").get_json()
    assert d["period"] == "2025-11" and d["check"]["n"] > 0

    old = client.post("/api/loop/add-month", data={"monthly": csv(mon[mon["period"] == "2025-05"])},
                      content_type="multipart/form-data")
    assert old.status_code == 400 and "after 2025-11" in old.get_json()["error"]


def test_ranked_employee_list_with_filters(client):
    d = client.get("/api/loop/employees?department=Sales&sort=score&page_size=10").get_json()
    assert d["available"] and len(d["rows"]) == 10 and d["total"] > 10
    assert {r["department"] for r in d["rows"]} == {"Sales"}
    scores = [r["cbi_work_score"] for r in d["rows"] if r["cbi_work_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert d["facets"]["teams"] and "Sales" in d["facets"]["departments"]

    high = client.get("/api/loop/employees?workload=high&flagged=1").get_json()
    assert all(r["workload_level"] == "high" and r["flagged"] for r in high["rows"])
    one = client.get("/api/loop/employees?q=SYN-00017").get_json()
    assert [r["employee_id"] for r in one["rows"]] == ["SYN-00017"]
