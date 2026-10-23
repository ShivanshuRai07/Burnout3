"""Stage 3 - Simulate: project an employee's score a few months ahead under different scenarios.

The forecast model is applied month by month; each step adds a random residual drawn from the
model's held-out error, so the result is a fan of possible paths rather than one line.
Scenarios either change work inputs (e.g. overtime -5 h) or add the observed effect of an
intervention type measured by the learning stage. Results are model-based scenarios, not promises.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from burnoutiq.predict import ForecastModel


def simulate_paths(model: ForecastModel, record: pd.Series, months: int = 3, n_paths: int = 500,
                   changes: dict[str, float] | None = None, monthly_effect: float = 0.0,
                   effect_months: int = 0, seed: int = 0) -> pd.DataFrame:
    """Return per-month percentiles (p10, p50, p90) of the simulated CBI score."""
    rng = np.random.default_rng(seed)
    x = pd.DataFrame([record.reindex(model.features)] * n_paths).reset_index(drop=True)
    for col, delta in (changes or {}).items():
        if col in x.columns:
            x[col] = pd.to_numeric(x[col], errors="coerce") + delta
            if col.endswith("_per_week") or col == "pto_days_taken":
                x[col] = x[col].clip(lower=0)
    rows = []
    for m in range(1, months + 1):
        score = model.predict_mean(x) + rng.normal(0, model.residual_sd, n_paths)
        if m <= effect_months:
            score = score + monthly_effect
        score = np.clip(score, 0, 100)
        x["cbi_work_score"] = score
        rows.append({"month_ahead": m, "p10": np.percentile(score, 10), "p50": np.percentile(score, 50),
                     "p90": np.percentile(score, 90), "share_high": float((score >= 50).mean())})
    return pd.DataFrame(rows).round(2)


def scenarios(model: ForecastModel, record: pd.Series, effects: pd.DataFrame | None = None,
              months: int = 3, extra: dict[str, dict[str, float]] | None = None) -> dict[str, pd.DataFrame]:
    """'no_change', any work-input scenarios in `extra`, and one scenario per intervention type
    whose effect was estimated (column simulation_effect, total change over duration_months)."""
    out = {"no_change": simulate_paths(model, record, months)}
    for name, changes in (extra or {}).items():
        out[name] = simulate_paths(model, record, months, changes=changes)
    if effects is not None and not effects.empty:
        for _, e in effects.dropna(subset=["simulation_effect"]).iterrows():
            dur = max(int(e.get("duration_months", 3)), 1)
            out[e["intervention_type"]] = simulate_paths(
                model, record, months, monthly_effect=e["simulation_effect"] / dur, effect_months=dur)
    return out
