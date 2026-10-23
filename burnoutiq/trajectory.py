"""Trajectory-based detection: flag sustained or reliably rising burnout, and people who go quiet after a high score.

Burnout is chronic, so one month over the threshold is a "watch", not a flag. A person is flagged when

  sustained high   - this survey and the previous one (within 3 months) are both >= 50
  reliable rise    - this survey is above the person's own baseline by more than the reliable change
                     index (RCI), i.e. beyond the questionnaire's measurement noise, and >= 40
  quiet after high - no survey this month, and the last survey within 3 months was >= 50
                     (people under strain answer surveys less often, so a missed survey after a high
                     score is treated as a signal, not as "no data")

Every feature is computed from months up to and including the period being assessed; nothing looks ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from burnoutiq.assess import HIGH

LOOKBACK = 3            # months searched back for the previous survey
RISE_FLOOR = 40.0       # a reliable rise only counts from this score up
LEVELS = ("sustained_high", "reliable_rise", "quiet_after_high")
REASONS = {"sustained_high": "high two surveys running", "reliable_rise": "rise beyond noise vs own baseline",
           "quiet_after_high": "missed survey after a high score"}


def _months(period: str, back: int) -> list[str]:
    p = pd.Period(period, freq="M")
    return [str(p - k) for k in range(1, back + 1)]


def history_features(records: pd.DataFrame, period: str, baseline_window: int = 3) -> pd.DataFrame:
    """One row per employee with a record in `period`: current score plus their recent history.

    records: monthly rows (employee_id, period, cbi_work_score); a row with no score = survey not answered.
    """
    cur = records[records["period"] == period][["employee_id", "cbi_work_score"]].drop_duplicates("employee_id")
    past = records[records["period"] < period]
    window = past[past["period"].isin(_months(period, LOOKBACK))]

    answered = window[window["cbi_work_score"].notna()].sort_values("period")
    last = answered.groupby("employee_id").tail(1).set_index("employee_id")
    # months in the lookback window that had a record but no answer
    unanswered = window.assign(miss=window["cbi_work_score"].isna())
    missed = unanswered.groupby("employee_id")["miss"].sum()
    # consecutive unanswered months ending just before this one (newest month first)
    miss_by_month = unanswered.pivot_table(index="employee_id", columns="period", values="miss", aggfunc="max")
    streak = pd.Series(0, index=miss_by_month.index)
    alive = pd.Series(True, index=miss_by_month.index)
    for m in _months(period, LOOKBACK):
        col = miss_by_month[m].fillna(0).astype(bool) if m in miss_by_month else pd.Series(False, index=miss_by_month.index)
        alive &= col
        streak += alive.astype(int)

    base_src = past[past["cbi_work_score"].notna()].sort_values("period").groupby("employee_id").tail(baseline_window)
    base = base_src.groupby("employee_id")["cbi_work_score"].agg(["mean", "count"])
    baseline = base["mean"].where(base["count"] >= baseline_window)

    out = cur.rename(columns={"cbi_work_score": "score_now"}).set_index("employee_id")
    out["answered_now"] = out["score_now"].notna()
    out["prev_score"] = last["cbi_work_score"]
    out["prev_period"] = last["period"]
    out["missed_last3"] = missed.reindex(out.index).fillna(0).astype(int)
    out["missed_streak"] = streak.reindex(out.index).fillna(0).astype(int) + (~out["answered_now"]).astype(int)
    out["baseline"] = baseline.reindex(out.index)
    out["change_vs_baseline"] = out["score_now"] - out["baseline"]
    # latest known score: this month if answered, otherwise the last answer in the lookback window
    out["latest_known"] = out["score_now"].fillna(out["prev_score"])
    hist_high = answered.assign(h=answered["cbi_work_score"] >= HIGH).groupby("employee_id")["h"].sum()
    out["high_last3"] = hist_high.reindex(out.index).fillna(0).astype(int) + (out["score_now"] >= HIGH).astype(int)
    return out.reset_index()


def trajectory_flags(feats: pd.DataFrame, rci: float) -> pd.DataFrame:
    """Adds sustained_high / reliable_rise / quiet_after_high, `trajectory_flag`, a reason string and a level.

    level: flagged (any of the three) / watch (one high month, not yet sustained) / ok / no_data
    """
    df = feats.copy()
    now, prev = df["score_now"], df["prev_score"]
    df["sustained_high"] = (now >= HIGH) & (prev >= HIGH)
    df["reliable_rise"] = (df["change_vs_baseline"] >= rci) & (now >= RISE_FLOOR)
    df["quiet_after_high"] = now.isna() & (prev >= HIGH)
    flags = df[list(LEVELS)].fillna(False).astype(bool)
    df["trajectory_flag"] = flags.any(axis=1)
    df["trajectory_reasons"] = flags.apply(lambda r: "; ".join(REASONS[c] for c in LEVELS if r[c]), axis=1)
    watch = (now >= HIGH) & ~df["trajectory_flag"]
    no_data = now.isna() & prev.isna()
    df["trajectory_level"] = np.select([df["trajectory_flag"], watch, no_data], ["flagged", "watch", "no_data"], default="ok")
    return df
