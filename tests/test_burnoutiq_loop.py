"""Tests for the burnoutiq loop package (Assess -> Predict -> Simulate -> Intervene -> Verify -> Learn)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from burnoutiq import BurnoutLoop
from burnoutiq.assess import score_cbi
from burnoutiq.reference import division_summary, employee_flags, quadrant
from burnoutiq.schema import InputError, validate, write_templates
from burnoutiq.verify import classify_change, reliable_change_threshold

DATA = Path(__file__).resolve().parent.parent / "Datasets" / "burnoutiq_dataset" / "data"


@pytest.fixture(scope="module")
def loop():
    return BurnoutLoop.from_csv(DATA / "employees.csv", DATA / "assessments.csv", DATA / "interventions.csv").fit()


def items(*rows):
    return pd.DataFrame(rows, columns=[f"cbi_w{i}" for i in range(1, 8)])


def test_cbi_scoring_reverses_item_7_and_needs_four_items():
    s = score_cbi(items([100, 100, 100, 100, 100, 100, 0], [100, 100, 100, np.nan, np.nan, np.nan, np.nan]))
    assert s.iloc[0] == 100.0
    assert np.isnan(s.iloc[1])


def test_verify_thresholds():
    rci = reliable_change_threshold(17.5, 0.87)
    assert 17 < rci < 18
    out = classify_change(pd.Series([-20.0, -6.0, 2.0, 7.0, np.nan]), rci)
    assert out["outcome"].tolist() == ["improved", "improved", "no_change", "worsened", "no_follow_up"]
    assert out["reliable_change"].tolist() == [True, False, False, False, False]


def test_validation_reports_and_drops_bad_rows():
    emp = pd.DataFrame({"employee_id": ["A", "B"], "department": ["X", "X"]})
    mon = pd.DataFrame({"employee_id": ["A", "A", "C", "B"], "period": ["2025-01", "2025/02", "2025-01", "2025-01"],
                        **{f"cbi_w{i}": [50, 50, 50, 120] for i in range(1, 8)}})
    v = validate(emp, mon)
    assert len(v.monthly) == 2
    assert v.monthly["cbi_w1"].isna().sum() == 1
    assert len(v.issues) == 2 + 7   # bad period, unknown employee, one out-of-range value per CBI item
    with pytest.raises(InputError):
        validate(emp, mon.drop(columns="cbi_w3"))


def test_templates_written(tmp_path):
    paths = write_templates(tmp_path)
    assert {p.name for p in paths} == {"employees_template.csv", "monthly_template.csv", "interventions_template.csv"}


def test_everyone_overworked_division_is_systemic_not_hidden():
    n = 12
    cur = pd.DataFrame({"employee_id": [f"E{i}" for i in range(n)], "period": "2025-06", "department": "Ops",
                        "cbi_work_score": np.linspace(55, 70, n), "work_hours_per_week": 52.0})
    flags = employee_flags(cur, cur)
    div = division_summary(flags)
    assert bool(div.loc[0, "systemic"])
    assert (quadrant(flags, div) == "individual_and_systemic").all()


def test_forecast_beats_persistence_with_honest_interval(loop):
    m = loop.model.metrics
    assert m["beats_persistence"]
    assert 0.92 <= m["interval_95_coverage"] <= 0.98


def test_run_gives_every_employee_a_status(loop):
    res = loop.run("2025-06")
    emp = res.employees
    assert emp["status"].notna().all()
    assert (emp.loc[emp["cbi_work_score"].isna() & ~emp["flagged"], "quadrant"] == "no_score").all()
    assert res.company["employees_scored"] == emp["cbi_work_score"].notna().sum()


def test_status_never_uses_future_follow_ups(loop):
    res = loop.run("2025-03")
    outcomes = res.employees[res.employees["status"].str.startswith("outcome_")]
    iv = loop.linked.set_index("employee_id")
    for eid in outcomes["employee_id"]:
        periods = iv.loc[[eid], "follow_up_score_period"].dropna()
        assert (periods <= "2025-03").any()


def test_randomised_pilot_preferred_for_simulation(loop):
    eff = loop.effects.set_index("intervention_type")
    rand = loop.randomised
    assert rand is not None and rand["ci_low"] < rand["ci_high"]
    assert eff.loc[rand["intervention_type"], "evidence"].startswith("randomised")
    assert eff.loc[rand["intervention_type"], "simulation_effect"] == rand["difference"]


def test_employee_profile_has_forecast_and_scenarios(loop):
    p = loop.employee("SYN-00017")
    assert p["forecast"] is not None and p["forecast"]["forecast_low"] <= p["forecast"]["forecast"] <= p["forecast"]["forecast_high"]
    assert "no_change" in p["scenarios"] and "overtime_minus_5h" in p["scenarios"]
    assert len(p["scenarios"]["no_change"]) == 3
