"""Trajectory-based detection: sustained high, reliable rise, quiet after a high score, and one-month watch."""
import numpy as np
import pandas as pd

from burnoutiq.trajectory import history_features, trajectory_flags

RCI = 17.8
MONTHS = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]


def _records(rows: dict) -> pd.DataFrame:
    """rows: employee -> list of scores per month (None = record but no answer)."""
    return pd.DataFrame([{"employee_id": e, "period": p, "cbi_work_score": np.nan if s is None else s}
                         for e, scores in rows.items() for p, s in zip(MONTHS, scores)])


def _levels(rows: dict, period: str = "2025-05") -> pd.Series:
    out = trajectory_flags(history_features(_records(rows), period), RCI)
    return out.set_index("employee_id")["trajectory_level"]


def test_sustained_high_is_flagged_one_high_month_is_watch():
    # one_high: 45 -> 55 is over the line once and within noise of their own baseline
    lv = _levels({"two_high": [30, 30, 30, 60, 62], "one_high": [45, 45, 45, 45, 55]})
    assert lv["two_high"] == "flagged"
    assert lv["one_high"] == "watch"


def test_reliable_rise_needs_more_than_measurement_noise():
    lv = _levels({"big_rise": [20, 20, 20, 22, 45], "small_rise": [30, 30, 30, 30, 45]})
    assert lv["big_rise"] == "flagged"        # +24 vs baseline 20.7, above RCI and >= 40
    assert lv["small_rise"] == "ok"           # +15 is within noise


def test_missed_survey_after_high_is_a_signal_not_no_data():
    feats = history_features(_records({"quiet": [40, 40, 58, None, None], "quiet_low": [20, 20, 20, 25, None]}), "2025-05")
    out = trajectory_flags(feats, RCI).set_index("employee_id")
    assert out.loc["quiet", "trajectory_level"] == "flagged"
    assert out.loc["quiet", "missed_streak"] == 2
    assert out.loc["quiet_low", "trajectory_level"] == "ok"


def test_no_history_and_no_answer_is_no_data():
    assert _levels({"new": [None, None, None, None, None]})["new"] == "no_data"


def test_loop_uses_trajectory_flag_and_keeps_reference_flag():
    from burnout_platform.longitudinal import LongitudinalTracker
    res = LongitudinalTracker().loop.run(None).employees
    assert {"trajectory_level", "reference_flag", "context_reasons"} <= set(res.columns)
    assert (res["flagged"] == (res["trajectory_level"] == "flagged")).all()
    # people who skipped this month's survey can be flagged now
    assert (res["flagged"] & res["cbi_work_score"].isna()).any()
