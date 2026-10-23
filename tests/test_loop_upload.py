"""Running the loop on uploaded CSV files (POST /api/loop/upload) and returning to the demo data."""
import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest

from api.index import app, get_state

DATA = Path(__file__).resolve().parent.parent / "Datasets" / "burnoutiq_dataset" / "data"
RECORDS = Path(__file__).resolve().parent.parent / "artifacts" / "intervention_records.json"


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


@pytest.fixture(scope="module")
def company():
    """A smaller 'company': the first 300 employees of the synthetic panel, without assessment dates."""
    emp = pd.read_csv(DATA / "employees.csv").head(300)
    ids = set(emp["employee_id"])
    mon = pd.read_csv(DATA / "assessments.csv")
    mon = mon[mon["employee_id"].isin(ids)].drop(columns=["assessment_date"])
    iv = pd.read_csv(DATA / "interventions.csv")
    return emp, mon, iv[iv["employee_id"].isin(ids)]


def csv(df):
    return (io.BytesIO(df.to_csv(index=False).encode()), "f.csv")


def upload(client, **frames):
    return client.post("/api/loop/upload", data={k: csv(v) for k, v in frames.items()},
                       content_type="multipart/form-data")


def test_upload_runs_loop_on_company_data(client, company):
    emp, mon, iv = company
    before = hashlib.sha256(RECORDS.read_bytes()).hexdigest() if RECORDS.exists() else None
    res = upload(client, employees=emp, monthly=mon, interventions=iv)
    assert res.status_code == 200, res.get_json()
    src = res.get_json()["source"]
    assert src["kind"] == "upload" and src["employees"] == 300

    loop = client.get("/api/loop").get_json()
    assert loop["source"]["kind"] == "upload"
    assert loop["company"]["employees_total"] == 300
    assert "Computed from" in loop["notice"]
    assert client.get("/api/forecast").get_json()["source"]["kind"] == "upload"

    eid = emp["employee_id"].iat[0]
    prof = client.get(f"/api/search-employee?id={eid}").get_json()
    assert prof.get("longitudinal", {}).get("is_longitudinal")

    # uploaded data is never written over the demo's saved intervention records
    after = hashlib.sha256(RECORDS.read_bytes()).hexdigest() if RECORDS.exists() else None
    assert before == after


def test_reset_returns_to_demo(client, company):
    emp, mon, iv = company
    upload(client, employees=emp, monthly=mon, interventions=iv)
    res = client.post("/api/loop/reset")
    assert res.get_json()["source"]["kind"] == "demo"
    assert client.get("/api/loop").get_json()["company"]["employees_total"] == 2289


def test_survey_only_upload_is_level_1(client, company):
    emp, mon, _ = company
    survey_only = mon[["employee_id", "period"] + [f"cbi_w{i}" for i in range(1, 8)]]
    res = upload(client, employees=emp[["employee_id", "department"]], monthly=survey_only)
    assert res.status_code == 200, res.get_json()
    assert client.get("/api/loop").get_json()["forecast_metrics"]["test_pairs"] > 0


def test_unusable_files_give_clear_errors(client, company):
    emp, mon, _ = company
    res = upload(client, employees=emp, monthly=mon.drop(columns=["cbi_w3"]))
    assert res.status_code == 400 and "cbi_w3" in res.get_json()["error"]

    one_month = mon[mon["period"] == mon["period"].min()]
    res = upload(client, employees=emp, monthly=one_month)
    assert res.status_code == 400 and "consecutive-month pairs" in res.get_json()["error"]

    res = client.post("/api/loop/upload", data={"monthly": csv(mon)}, content_type="multipart/form-data")
    assert res.status_code == 400 and "required" in res.get_json()["error"]
    assert client.get("/api/loop").get_json()["source"]["kind"] == "demo"
