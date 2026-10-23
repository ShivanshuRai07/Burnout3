"""Validation and safe input mapping module for the Burnout Platform.

Ensures:
- Robust input parsing, range validation, and missing-value handling
- Standardized categorical casing and normalization
- Rescaling of UI 1-10 slider inputs to underlying model domain space
- Safe fallback to master dataset medians/modes for unsupplied parameters
- Strict non-diagnostic notice attached to all inferences
"""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple
import numpy as np
import pandas as pd

NON_DIAGNOSTIC_NOTICE = (
    "Decision-support only. This assessment evaluates workplace telemetry for "
    "organizational workload management and is not a medical diagnosis or clinical evaluation."
)

EVALUATION_THRESHOLD = 3.70
PROBABILITY_THRESHOLD = 33.0  # Percentage corresponding to optimal validation threshold tau = 0.33

CANONICAL_ROLES = [
    "Backend Developer", "Frontend Developer", "Devops", "Data Scientist",
    "Software Engineer", "Product Manager", "Qa Engineer", "Ml Engineer",
    "Sales Associate", "It Admin", "Hr Specialist", "Customer Support",
    "Project Manager", "Marketing Manager", "Unknown",
]

ROLE_LOOKUP = {r.lower(): r for r in CANONICAL_ROLES}
ROLE_LOOKUP.update({
    "devops engineer": "Devops",
    "qa": "Qa Engineer",
    "ml": "Ml Engineer",
    "machine learning engineer": "Ml Engineer",
    "developer": "Software Engineer",
    "coder": "Software Engineer",
    "programmer": "Software Engineer",
    "swe": "Software Engineer",
    "sde": "Software Engineer",
    "pm": "Product Manager",
    "hr": "Hr Specialist",
})

WORK_MODE_LOOKUP = {
    "hybrid": "Hybrid",
    "remote": "Remote",
    "onsite": "Onsite",
    "on-site": "Onsite",
    "in-office": "Onsite",
    "office": "Onsite",
    "wfh": "Remote",
    "unknown": "Unknown",
}

COMPANY_SIZE_LOOKUP = {
    "startup": "Startup",
    "mid-size": "Mid-size",
    "midsize": "Mid-size",
    "medium": "Medium",
    "large": "Large",
    "mnc": "MNC",
    "enterprise": "MNC",
    "unknown": "Unknown",
}

NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "work_hours_per_week": (0.0, 168.0),
    "overtime_hours": (0.0, 80.0),
    "meetings_per_day": (0.0, 30.0),
    "deadlines_missed": (0.0, 50.0),
    "experience_years": (0.0, 60.0),
    "stress_level": (0.0, 10.0),
    "sleep_hours": (0.0, 24.0),
    "screen_time_hours": (0.0, 24.0),
    "caffeine_intake": (0.0, 30.0),
    "physical_activity_days": (0.0, 7.0),
    "social_support_score": (0.0, 100.0),
    "work_life_balance": (0.0, 200.0),
    "job_satisfaction": (0.0, 200.0),
    "manager_support": (0.0, 200.0),
}


def clean_categorical(val: Any, lookup_map: dict[str, str], default_val: str) -> str:
    """Normalize categorical string values with fallback to default."""
    if val is None:
        return default_val
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return default_val
    return lookup_map.get(s.lower(), s.title())


def validate_and_clean_payload(payload: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Validate, sanitize, and map scenario prediction payload into model feature space.
    
    Raises:
        ValueError: When inputs cannot be parsed, are out of domain boundaries, or non-finite.
    """
    if not isinstance(payload, dict):
        raise ValueError("Prediction payload must be a JSON object / dictionary.")

    cleaned: dict[str, Any] = {}

    # 1. Numerical Features
    for col, (min_b, max_b) in NUMERIC_BOUNDS.items():
        if col in payload and payload[col] not in (None, ""):
            raw_val = payload[col]
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                raise ValueError(f"Feature '{col}' must be a valid number, got: {raw_val!r}")

            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"Feature '{col}' cannot be NaN or infinite.")

            if val < min_b:
                raise ValueError(f"Feature '{col}' cannot be less than {min_b} (received {val}).")
            if val > max_b:
                raise ValueError(f"Feature '{col}' cannot exceed maximum limit of {max_b} (received {val}).")

            # UI Slider scale alignment:
            # Dashboard sliders for work_life_balance, manager_support, and job_satisfaction
            # operate on a 1-10 scale in UI, while the underlying model dataset uses 20-200.
            # If input <= 10.0 and positive, map to the 20-200 scale (1 -> 20, 5 -> 100, 10 -> 200).
            if col in {"work_life_balance", "manager_support", "job_satisfaction"}:
                if 0.0 < val <= 10.0:
                    val = val * 20.0

            cleaned[col] = float(val)
        else:
            cleaned[col] = float(defaults.get(col, 0.0))

    # 2. Categorical Features
    cleaned["job_role"] = clean_categorical(payload.get("job_role"), ROLE_LOOKUP, defaults.get("job_role", "Unknown"))
    cleaned["work_mode"] = clean_categorical(payload.get("work_mode"), WORK_MODE_LOOKUP, defaults.get("work_mode", "Unknown"))
    cleaned["company_size"] = clean_categorical(payload.get("company_size"), COMPANY_SIZE_LOOKUP, defaults.get("company_size", "Unknown"))

    return cleaned


from burnout_platform.insights import (
    build_workplace_insight_bundle,
    ESTIMATION_ERROR_MARGIN,
    PROHIBITED_USES,
)


def compute_prediction_result(
    row_eng: pd.DataFrame,
    score_model: Any,
    risk_model: Any,
    threshold: float = EVALUATION_THRESHOLD,
    cleaned_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute inference for regression and calibrated risk classification with Phase 4 safeguards."""
    raw_score = float(score_model.predict(row_eng)[0])
    score = round(float(np.clip(raw_score, 0.0, 10.0)), 2)

    raw_prob = float(risk_model.predict_proba(row_eng)[0, 1])
    elevated_prob = round(float(np.clip(raw_prob * 100.0, 0.0, 100.0)), 1)

    if score >= threshold:
        band = "Elevated"
    elif score >= 2.5:
        band = "Moderate"
    else:
        band = "Low"

    obs_dict = cleaned_inputs if cleaned_inputs is not None else row_eng.iloc[0].to_dict()
    insights_bundle = build_workplace_insight_bundle(obs_dict, score, elevated_prob, band, threshold)

    lower_bound = round(max(0.0, score - ESTIMATION_ERROR_MARGIN), 2)
    upper_bound = round(min(10.0, score + ESTIMATION_ERROR_MARGIN), 2)

    return {
        "burnout_score": score,
        "elevated_risk_probability": elevated_prob,
        "risk_band": band,
        "threshold": threshold,
        "probability_threshold": PROBABILITY_THRESHOLD,
        "is_elevated_risk": bool(score >= threshold or elevated_prob >= PROBABILITY_THRESHOLD),
        "is_medical_diagnosis": False,
        "uncertainty_interval": [lower_bound, upper_bound],
        "workplace_indicators": insights_bundle["workplace_indicators"],
        "suggested_actions": insights_bundle["suggested_actions"],
        "responsible_use_safeguards": insights_bundle["responsible_use_safeguards"],
        "insights": insights_bundle,
        "notice": NON_DIAGNOSTIC_NOTICE,
    }
