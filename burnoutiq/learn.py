"""Outer loop - the organisation learns which interventions are followed by improvement.

A raw before/after change overstates effects: people are referred when their score is unusually
high, and high scores tend to fall anyway (regression to the mean). So every intervention is compared
with a matched comparison group: employees with no intervention in the same window whose score in the
referral month was within MATCH_WINDOW points of the person's baseline. The adjusted difference
(observed change minus comparison change) is still observational, not a proven causal effect: people
are also referred for reasons the data does not record, which keeps their burnout high (confounding by
indication). On the synthetic panel, where true effects are known, the adjusted difference was 3-4 points
too close to "no effect" for every type, while the randomised pilot recovered the true effect.
Where a randomised pilot exists (trial_arm treatment/control) its estimate is preferred for simulation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MATCH_WINDOW = 5.0
MIN_COMPARISON = 5


def _ci(x: pd.Series) -> tuple[float, float]:
    x = x.dropna()
    if len(x) < 2:
        return (np.nan, np.nan)
    half = 1.96 * x.std(ddof=1) / np.sqrt(len(x))
    return (round(x.mean() - half, 2), round(x.mean() + half, 2))


def comparison_change(linked: pd.DataFrame, scores: pd.DataFrame) -> pd.Series:
    """Mean change of matched, untreated employees over each intervention's baseline -> follow-up window."""
    s = scores.pivot_table(index="employee_id", columns="period", values="cbi_work_score")
    treated_windows = linked[["employee_id", "referral_period", "follow_up_period"]].dropna()
    out = pd.Series(np.nan, index=linked.index)
    usable = linked.dropna(subset=["baseline_score", "follow_up_score"])
    for (r, f), grp in usable.groupby(["referral_period", "follow_up_score_period"]):
        if r not in s.columns or f not in s.columns:
            continue
        busy = treated_windows[(treated_windows["referral_period"] <= f) & (treated_windows["follow_up_period"] >= r)]
        pool = s.loc[~s.index.isin(busy["employee_id"]), [r, f]].dropna()
        if pool.empty:
            continue
        base, change = pool[r].to_numpy(), (pool[f] - pool[r]).to_numpy()
        for i, b in grp["baseline_score"].items():
            near = np.abs(base - b) <= MATCH_WINDOW
            if near.sum() >= MIN_COMPARISON:
                out[i] = change[near].mean()
    return out


def effect_table(linked: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    iv = linked.copy()
    iv["comparison_change"] = comparison_change(iv, scores)
    iv["adjusted"] = iv["observed_change"] - iv["comparison_change"]
    iv["duration_months"] = (pd.PeriodIndex(iv["end_period"].fillna(iv["follow_up_period"]), freq="M")
                             - pd.PeriodIndex(iv["referral_period"], freq="M")).map(lambda d: d.n)
    rows = []
    for itype, g in iv[iv["completion_status"] != "not_applicable"].groupby("intervention_type"):
        f = g[g["follow_up_score"].notna()]
        rows.append({
            "intervention_type": itype, "n": len(g), "n_followed_up": len(f),
            "improved": int((f["outcome"] == "improved").sum()), "no_change": int((f["outcome"] == "no_change").sum()),
            "worsened": int((f["outcome"] == "worsened").sum()),
            "reliable_improvement": int(((f["outcome"] == "improved") & f["reliable_change"]).sum()),
            "mean_observed_change": round(f["observed_change"].mean(), 2),
            "mean_comparison_change": round(f["comparison_change"].mean(), 2),
            "adjusted_difference": round(f["adjusted"].mean(), 2),
            "adjusted_ci_low": _ci(f["adjusted"])[0], "adjusted_ci_high": _ci(f["adjusted"])[1],
            "n_matched": int(f["adjusted"].notna().sum()),
            "duration_months": int(g["duration_months"].median()),
        })
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    # Observational estimates are only simulated when clearly beneficial (whole CI below zero)
    clear = table["adjusted_ci_high"] < 0
    table["simulation_effect"] = table["adjusted_difference"].where(clear)
    table["evidence"] = np.where(clear, "observational, may be biased", "observational, no reliable effect (not simulated)")
    rand = randomised_estimate(linked)
    if rand:
        hit = table["intervention_type"] == rand["intervention_type"]
        table.loc[hit, "simulation_effect"] = rand["difference"]
        table.loc[hit, "evidence"] = f"randomised pilot (n={rand['n_treatment']}+{rand['n_control']})"
    return table


def randomised_estimate(linked: pd.DataFrame) -> dict | None:
    if "trial_arm" not in linked or not linked["trial_arm"].isin(["treatment", "control"]).any():
        return None
    f = linked[linked["follow_up_score"].notna()]
    t = f.loc[f["trial_arm"] == "treatment", "observed_change"]
    c = f.loc[f["trial_arm"] == "control", "observed_change"]
    if len(t) < 2 or len(c) < 2:
        return None
    diff = t.mean() - c.mean()
    se = np.sqrt(t.var(ddof=1) / len(t) + c.var(ddof=1) / len(c))
    return {"n_treatment": int(len(t)), "n_control": int(len(c)), "difference": round(diff, 2),
            "ci_low": round(diff - 1.96 * se, 2), "ci_high": round(diff + 1.96 * se, 2),
            "intervention_type": linked.loc[linked["trial_arm"] == "treatment", "intervention_type"].mode().iat[0]}


def calibration_check(model, records: pd.DataFrame) -> pd.DataFrame:
    """Mean forecast vs mean actual next-month score per department (calibration-in-the-large)."""
    from burnoutiq.predict import transition_pairs
    pairs = transition_pairs(records)
    if pairs.empty:
        return pd.DataFrame()
    pairs["pred"] = model.predict_mean(pairs)
    g = pairs.groupby("department").agg(n=("pred", "size"), mean_forecast=("pred", "mean"),
                                        mean_actual=("target_next", "mean"))
    g["bias"] = g["mean_forecast"] - g["mean_actual"]
    g["needs_recalibration"] = g["bias"].abs() > 3
    return g.round(2).reset_index()
