"""Workplace insights, pattern translation, and non-medical suggestions module.

Translates validated model outputs and numerical telemetry into:
- Human-understandable workplace indicators (Workload, Meetings, Deadlines, Rest)
- Operational, non-medical intervention suggestions (e.g. overtime caps, meeting detox)
- Strict separation between model predictions, observed data, and suggested actions
- Quantification of estimation uncertainty (empirical RMSE ±0.56 margin)
"""
from __future__ import annotations

from typing import Any, Dict, List
import numpy as np

# Empirical error margin from Phase 2 benchmark evaluation (Test RMSE = 0.5634)
ESTIMATION_ERROR_MARGIN = 0.56

PROHIBITED_USES = [
    "Adverse employment decisions (termination, demotion, penalty)",
    "Hiring or promotion gating without holistic human evaluation",
    "Clinical diagnosis or substitute for medical treatment",
    "Automated punitive workload enforcement",
    "Public or team-wide ranking and shaming",
]


def assess_workplace_indicators(observed: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Translate raw numerical inputs into operational workplace indicator status."""
    hours = float(observed.get("work_hours_per_week", 40.0))
    overtime = float(observed.get("overtime_hours", 0.0))
    meetings = float(observed.get("meetings_per_day", 3.0))
    deadlines = float(observed.get("deadlines_missed", 0.0))
    sleep = float(observed.get("sleep_hours", 7.0))
    stress = float(observed.get("stress_level", 5.0))

    # 1. Workload Intensity
    if hours >= 52.0 or overtime >= 8.0:
        workload_lvl = "Elevated"
        workload_detail = f"Extended hours ({hours:.0f}h/wk total, {overtime:.0f}h overtime)"
    elif hours >= 44.0 or overtime >= 4.0:
        workload_lvl = "Moderate"
        workload_detail = f"Above-standard hours ({hours:.0f}h/wk total, {overtime:.0f}h overtime)"
    else:
        workload_lvl = "Sustainable"
        workload_detail = f"Standard workload ({hours:.0f}h/wk total, {overtime:.0f}h overtime)"

    # 2. Meeting Density
    if meetings >= 5.0:
        meeting_lvl = "High"
        meeting_detail = f"{meetings:.1f} meetings/day (high calendar fragmentation)"
    elif meetings >= 3.5:
        meeting_lvl = "Moderate"
        meeting_detail = f"{meetings:.1f} meetings/day (standard collaboration load)"
    else:
        meeting_lvl = "Low"
        meeting_detail = f"{meetings:.1f} meetings/day (ample deep-work focus time)"

    # 3. Milestone & Delivery Pace
    if deadlines >= 3.0:
        deadline_lvl = "Friction"
        deadline_detail = f"{deadlines:.0f} missed deadlines (delivery friction or scope mismatch)"
    elif deadlines >= 1.0:
        deadline_lvl = "Monitored"
        deadline_detail = f"{deadlines:.0f} missed deadline (occasional delivery delay)"
    else:
        deadline_lvl = "Smooth"
        deadline_detail = "Zero missed deadlines reported"

    # 4. Rest & Recovery Boundary
    if sleep < 6.0:
        rest_lvl = "Constrained"
        rest_detail = f"{sleep:.1f}h nightly rest (potential recovery deficit)"
    elif sleep <= 7.0:
        rest_lvl = "Moderate"
        rest_detail = f"{sleep:.1f}h nightly rest (sufficient baseline)"
    else:
        rest_lvl = "Healthy"
        rest_detail = f"{sleep:.1f}h nightly rest (optimal recovery window)"

    return {
        "workload_intensity": {"status": workload_lvl, "summary": workload_detail},
        "meeting_density": {"status": meeting_lvl, "summary": meeting_detail},
        "delivery_friction": {"status": deadline_lvl, "summary": deadline_detail},
        "rest_boundary": {"status": rest_lvl, "summary": rest_detail},
    }


def generate_actionable_suggestions(observed: dict[str, Any], risk_band: str) -> list[dict[str, str]]:
    """Derive simple, non-medical operational suggestions from observed telemetry.
    
    Suggestions strictly target workload allocation, meeting schedules, and managerial check-ins.
    No clinical or psychological interventions are prescribed.
    """
    suggestions: list[dict[str, str]] = []

    hours = float(observed.get("work_hours_per_week", 40.0))
    overtime = float(observed.get("overtime_hours", 0.0))
    meetings = float(observed.get("meetings_per_day", 3.0))
    deadlines = float(observed.get("deadlines_missed", 0.0))
    stress = float(observed.get("stress_level", 5.0))
    manager_support = float(observed.get("manager_support", 100.0))

    # Overtime guardrail
    if overtime >= 6.0:
        suggestions.append({
            "category": "Overtime Guardrail",
            "action": "Cap individual overtime at maximum 4h/week and protect weekends from task spillover.",
            "rationale": f"Employee logged {overtime:.1f}h overtime this week, which compounds fatigue.",
        })
    elif overtime >= 4.0:
        suggestions.append({
            "category": "Overtime Monitoring",
            "action": "Review ongoing overtime distribution across team members to prevent chronic accumulation.",
            "rationale": f"Overtime is elevated at {overtime:.1f}h/week.",
        })

    # Meeting detox
    if meetings >= 4.5:
        suggestions.append({
            "category": "Meeting Hygiene",
            "action": "Introduce meeting-free focus blocks (e.g. no-meeting mornings) and audit recurring invitations.",
            "rationale": f"High meeting load ({meetings:.1f} meetings/day) significantly disrupts deep-work execution.",
        })

    # Workweek workload rebalancing
    if hours >= 50.0:
        suggestions.append({
            "category": "Workload Rebalancing",
            "action": "Assess sprint commitments and redistribute non-critical tasks to bring workweek toward 40–42 hours.",
            "rationale": f"Total workload of {hours:.1f}h/week exceeds sustainable operating norms.",
        })

    # Milestone scoping
    if deadlines >= 2.0:
        suggestions.append({
            "category": "Milestone Scoping",
            "action": "Conduct backlog reprioritization and review task dependencies in the upcoming planning cycle.",
            "rationale": f"{deadlines:.0f} missed deadlines suggest scope overload or unrealistic delivery estimates.",
        })

    # Proactive supportive 1-on-1
    if stress >= 7.0 or manager_support < 80.0:
        suggestions.append({
            "category": "Managerial Check-in",
            "action": "Schedule a supportive 1-on-1 conversation focused on obstacle clearance and task reprioritization.",
            "rationale": "High stress friction combined with low support signals the need for supportive alignment.",
        })

    # Default baseline recommendation when in healthy range
    if not suggestions or risk_band == "Low":
        suggestions.append({
            "category": "Workload Maintenance",
            "action": "Maintain current workload balance, healthy pacing, and flexible scheduling policies.",
            "rationale": "Observed indicators align with sustainable operational performance.",
        })

    return suggestions[:3]  # Return top 3 most relevant actionable items


def build_workplace_insight_bundle(
    observed_inputs: dict[str, Any],
    score: float,
    prob: float,
    risk_band: str,
    threshold: float,
) -> dict[str, Any]:
    """Assemble complete structured insight bundle with explicit separation of concern."""
    lower_bound = round(max(0.0, score - ESTIMATION_ERROR_MARGIN), 2)
    upper_bound = round(min(10.0, score + ESTIMATION_ERROR_MARGIN), 2)

    indicators = assess_workplace_indicators(observed_inputs)
    suggestions = generate_actionable_suggestions(observed_inputs, risk_band)

    return {
        "model_prediction": {
            "estimated_burnout_score": score,
            "uncertainty_interval": [lower_bound, upper_bound],
            "estimation_rmse_margin": ESTIMATION_ERROR_MARGIN,
            "elevated_risk_probability": prob,
            "risk_band": risk_band,
            "operational_threshold": threshold,
        },
        "observed_workplace_telemetry": {
            k: v for k, v in observed_inputs.items()
            if k in {
                "work_hours_per_week", "overtime_hours", "meetings_per_day",
                "deadlines_missed", "stress_level", "sleep_hours",
                "job_role", "work_mode", "experience_years"
            }
        },
        "workplace_indicators": indicators,
        "suggested_actions": suggestions,
        "responsible_use_safeguards": {
            "is_medical_diagnosis": False,
            "decision_support_only": True,
            "prohibited_actions": PROHIBITED_USES,
            "advisory": (
                "BurnoutIQ estimates are organizational decision-support indicators, NOT medical diagnoses. "
                "Predictions must NEVER be used to penalize, terminate, demote, or discipline employees. "
                "Always verify indicators through voluntary, empathetic human managerial conversations."
            ),
        },
    }
