"""Systems-Thinking Frameworks for BurnoutIQ.

Inspired by Donella Meadows' Leverage Points and Johnston et al.'s Intervention Level Framework (ILF).
Provides structured conceptual frameworks, layer definitions, systems leverage analysis,
code-level implementation references, and scientific boundary definitions.
"""

from __future__ import annotations
from typing import Any


def get_all_frameworks() -> dict[str, Any]:
    """Returns the five systems-thinking frameworks with full analytical depth and visual metadata."""
    return {
        "status": "success",
        "frameworks_count": 5,
        "philosophical_foundation": {
            "origin": "Donella Meadows (1999) 'Places to Intervene in a System' & Johnston et al. (2014) 'Intervention Level Framework'",
            "core_thesis": (
                "Workplace burnout is an emergent property of organizational systems dynamics, "
                "not an individual psychological failure. Addressing burnout effectively requires "
                "intervening at structural leverage points—information flows, feedback delays, "
                "operating rules, and cultural paradigms—rather than relying solely on surface-level "
                "coping events or isolated parameter tweaks."
            ),
            "scientific_disclaimer": (
                "BurnoutIQ distinguishes rigorously between statistical predictions, observed outcome associations, "
                "and causal proof. Score reductions following supportive interventions reflect observational evidence "
                "and must never be claimed as causal proofs without randomized counterfactual trial controls."
            )
        },
        "frameworks": [
            {
                "id": "burnout_prevention_leverage",
                "number": 1,
                "title": "Burnout Prevention Leverage Framework",
                "subtitle": "Workplace Culture, Policies, Team Structure, Feedback Loops, and Daily Work Conditions",
                "archetype": "Hierarchical Leverage Pyramid (5 Tiers: Events to Mindset)",
                "visual_type": "pyramid",
                "visual_asset_url": "/frameworks/01_burnout_prevention_leverage.jpg",
                "core_principle": (
                    "Intervening at the parameter level (e.g., wellness stipends or meditation apps) yields low, "
                    "transient impact because it leaves the structural rules and cultural incentives of overwork untouched. "
                    "Deep leverage requires ascending from surface symptoms into telemetry feedback loops, team topology, "
                    "policy guardrails, and psychological paradigms."
                ),
                "leverage_direction": "Bottom-to-Top (Ascending from low leverage events to deep systemic transformation)",
                "layers": [
                    {
                        "level": 1,
                        "position": "Apex / Deepest Leverage",
                        "name": "Cultural Paradigm & Mental Models",
                        "leverage_rating": "Transformational Leverage (Level 1)",
                        "color": "#ff5252",
                        "focus": "Organizational Mindset & Psychological Safety",
                        "description": (
                            "The shared unwritten beliefs, assumptions, and values that govern organizational behavior. "
                            "Shifts the paradigm from viewing burnout as 'individual weakness or lack of resilience' to "
                            "recognizing burnout as 'systemic operational friction and institutional debt'."
                        ),
                        "burnoutiq_manifestation": (
                            "Enforces non-punitive, non-diagnostic reporting. Establishes psychological safety where "
                            "employees can flag fatigue without career penalty. Prohibits using predictive scores for "
                            "performance evaluations or terminations."
                        ),
                        "counteracting_failure_mode": (
                            "Without paradigm change, managers weaponize telemetry data to micromanage rather than "
                            "support, turning predictive alerts into punitive surveillance."
                        )
                    },
                    {
                        "level": 2,
                        "position": "Tier 2 / High Leverage",
                        "name": "System Goals & Institutional Rules",
                        "leverage_rating": "High Structural Leverage (Level 2)",
                        "color": "#ffa726",
                        "focus": "Formal Operating Constraints & Policies",
                        "description": (
                            "The formal boundaries, incentive structures, and operational contracts that dictate how work happens. "
                            "Replaces implicit expectations of 24/7 availability with hard structural constraints."
                        ),
                        "burnoutiq_manifestation": (
                            "Hard limits on weekly overtime (45h ceiling alert), mandatory meeting-free focus days (e.g., 'Focus Fridays'), "
                            "strict rest boundaries between consecutive work shifts (≥11 hours), and formal PTO utilization requirements."
                        ),
                        "counteracting_failure_mode": (
                            "Without clear institutional policies, well-intentioned team norms erode under quarterly deadline pressure."
                        )
                    },
                    {
                        "level": 3,
                        "position": "Tier 3 / Medium-High Leverage",
                        "name": "Team Structure & Work Distribution",
                        "leverage_rating": "Structural Leverage (Level 3)",
                        "color": "#26a69a",
                        "focus": "Capacity Allocation & Redundancy",
                        "description": (
                            "How responsibilities, dependencies, and cognitive loads are architected across teams. "
                            "Eliminates critical single-person bottlenecks and balances sprint velocity with buffer reserves."
                        ),
                        "burnoutiq_manifestation": (
                            "Dynamic task redistribution playbooks, peer pairing on high-friction deliverables, "
                            "cross-training matrices, and automated escalation when an individual's delivery friction flags elevated."
                        ),
                        "counteracting_failure_mode": (
                            "Even dedicated employees collapse if team topology makes them an unbuffered single point of failure."
                        )
                    },
                    {
                        "level": 4,
                        "position": "Tier 4 / Medium Leverage",
                        "name": "Feedback Loops & Early Telemetry",
                        "leverage_rating": "Informational Leverage (Level 4)",
                        "color": "#5c6bc0",
                        "focus": "BurnoutIQ Predictive Detection & Signals",
                        "description": (
                            "The speed, accuracy, and distribution of information about emerging exhaustion. Bridges the "
                            "critical latency delay between physiological depletion and visible project delivery failure."
                        ),
                        "burnoutiq_manifestation": (
                            "Combines continuous workload telemetry (hours, overtime, meeting density, deadline pressure) "
                            "with calibrated elevated risk probabilities (threshold τ=0.33) and autoregressive CBI forecasting (t → t+1)."
                        ),
                        "counteracting_failure_mode": (
                            "Telemetry without action channels becomes inert noise; data must flow directly into actionable manager checklists."
                        )
                    },
                    {
                        "level": 5,
                        "position": "Base / Lowest Leverage",
                        "name": "Daily Work Conditions & Discrete Events",
                        "leverage_rating": "Parameter-Level Leverage (Level 5)",
                        "color": "#78909c",
                        "focus": "Immediate Task Friction & Isolated Symptoms",
                        "description": (
                            "The visible, day-to-day occurrences: calendar invites, Slack interruptions, emergency escalations, "
                            "and individual coping mechanisms (meditation apps, gym discounts, stress management webinars)."
                        ),
                        "burnoutiq_manifestation": (
                            "Real-time alerts for isolated meeting-heavy days or single-day overtime spikes, allowing rapid "
                            "micro-adjustments (e.g., declining non-essential syncs)."
                        ),
                        "counteracting_failure_mode": (
                            "Enterprise wellness programs spend 90% of their budgets here. Treating symptoms while ignoring "
                            "systemic workload rules leads to cynicism and accelerated employee turnover."
                        )
                    }
                ],
                "systems_takeaway": (
                    "Transformational burnout prevention occurs when Level 4 telemetry triggers Level 3 capacity reallocation, "
                    "enforced by Level 2 policy guardrails, and legitimized by a Level 1 cultural paradigm of psychological safety."
                )
            },
            {
                "id": "predict_intervene_verify",
                "number": 2,
                "title": "Predict → Intervene → Verify Framework",
                "subtitle": "The Closed-Loop Cybernetic Learning Cycle for Enterprise Wellbeing",
                "archetype": "Closed-Loop Cybernetic Feedback Cycle",
                "visual_type": "cycle",
                "visual_asset_url": "/frameworks/02_predict_intervene_verify.jpg",
                "core_principle": (
                    "Predictive intelligence without decisive human intervention is passive surveillance. "
                    "Supportive interventions without longitudinal verification are unvalidated speculation. "
                    "BurnoutIQ enforces an unbroken cybernetic loop connecting risk forecasting to verified human outcomes."
                ),
                "stages": [
                    {
                        "step": 1,
                        "name": "Predictive Forecasting",
                        "icon": "📈",
                        "color": "#2979ff",
                        "subheading": "Autoregressive Time-Series & Calibrated Risk",
                        "mechanics": (
                            "Ingests continuous workplace telemetry (hours, overtime, meetings, deadlines) and past assessment waves. "
                            "Runs the production Ridge forecasting model to project month t+1 Copenhagen Burnout Inventory (CBI) score "
                            "with empirical ±1.96 standard error intervals (±19.6 CBI pts). Simultaneously computes calibrated elevated risk probability."
                        ),
                        "artifact_connection": "artifacts/forecast_model.joblib & artifacts/elevated_risk_model.joblib"
                    },
                    {
                        "step": 2,
                        "name": "Evidence Interpretation & Triage",
                        "icon": "🔍",
                        "color": "#00e676",
                        "subheading": "Root-Cause Telemetry Deconstruction",
                        "mechanics": (
                            "Decomposes elevated risk into four non-diagnostic workplace friction indicators: "
                            "Workload Intensity (hours/overtime), Meeting Density (>4h/day), Delivery Friction (missed deadlines), "
                            "and Rest Boundary Erosion. Ranks cohorts into Critical Escalation (CBI ≥ 65), Follow-up Due, or Baseline."
                        ),
                        "artifact_connection": "burnout_platform/insights.py & /api/forecast?cohort=Engineering"
                    },
                    {
                        "step": 3,
                        "name": "Supportive Intervention Execution",
                        "icon": "🤝",
                        "color": "#ffd600",
                        "subheading": "Actionable Human Accommodation",
                        "mechanics": (
                            "Authorized HR or department leaders assign evidence-backed supportive actions from standardized categories: "
                            "Workload Cap Guardrail, Meeting Detox / Asynchronous Protocol, Peer Task Rebalancing, or Supportive 1:1 Check-in. "
                            "The action is stamped with employee ID, date, and trial arm into persistent storage."
                        ),
                        "artifact_connection": "artifacts/intervention_records.json & /api/interventions/record"
                    },
                    {
                        "step": 4,
                        "name": "Longitudinal Verification",
                        "icon": "🎯",
                        "color": "#ff3d00",
                        "subheading": "Follow-Up Wave Scoring & Delta Measurement",
                        "mechanics": (
                            "Following a minimum 30-day intervention implementation window, a subsequent assessment wave is collected. "
                            "The system computes the exact score delta: Δ = Score_{t+1} - Score_{t_0}. Automatically classifies the trajectory into "
                            "Improved (reduction ≥ 5.0 pts), Stable (within ±5.0 pts), or Worsened (increase ≥ 5.0 pts)."
                        ),
                        "artifact_connection": "/api/interventions/record-followup & longitudinal.py"
                    },
                    {
                        "step": 5,
                        "name": "Continuous Learning & Recalibration",
                        "icon": "🔄",
                        "color": "#d500f9",
                        "subheading": "Organizational Memory & Playbook Optimization",
                        "mechanics": (
                            "Aggregates intervention completion rates and verified recovery percentages across departments. "
                            "Identifies which accommodation types correlate with positive recovery in specific roles, updating organizational "
                            "playbooks while providing fresh held-out data to retrain predictive models without person leakage."
                        ),
                        "artifact_connection": "artifacts/intervention_records.json & train.py"
                    }
                ],
                "systems_takeaway": (
                    "This 5-stage loop prevents 'black hole wellness initiatives' where interventions are deployed without "
                    "baseline metrics, follow-up evaluations, or outcome ledgers."
                )
            },
            {
                "id": "workplace_feedback_loops",
                "number": 3,
                "title": "Workplace Burnout Feedback Loop Framework",
                "subtitle": "Causal Dynamics of Overwork Spirals vs. Proactive Resilience Stabilizers",
                "archetype": "Systems Dynamics Causal Loop Diagram (CLD)",
                "visual_type": "causal_loop",
                "visual_asset_url": "/frameworks/03_workplace_burnout_feedback_loops.jpg",
                "core_principle": (
                    "Burnout is not an acute, sudden event; it is a runaway reinforcing feedback loop. "
                    "When workload pressures produce fatigue, impaired cognitive throughput causes delivery friction, "
                    "which generates backlog and intensifies work pressure. Proactive intervention introduces a stabilizing "
                    "balancing loop that breaks this cycle before the tipping point."
                ),
                "loops": [
                    {
                        "id": "R1",
                        "type": "Reinforcing Loop (Vicious Cycle)",
                        "name": "The Overwork Death Spiral",
                        "color": "#ff5252",
                        "dynamics": "Runaway Acceleration (+ feedback)",
                        "nodes": [
                            {"order": 1, "name": "Workload & Project Pressure", "effect": "increases"},
                            {"order": 2, "name": "Excessive Overtime & Meeting Overload", "effect": "increases"},
                            {"order": 3, "name": "Cumulative Fatigue & Sleep Deficit", "effect": "increases with delay"},
                            {"order": 4, "name": "Cognitive Decline & Task Friction", "effect": "increases"},
                            {"order": 5, "name": "Missed Deadlines & Quality Defects", "effect": "increases"},
                            {"order": 6, "name": "Escalated Workload & Crisis Escalation", "effect": "feeds back to Node 1 (+)"}
                        ],
                        "systemic_danger": (
                            "Because of the biological delay between initial sleep deficit and visible cognitive decline, "
                            "teams assume they are coping effectively until they hit a sudden non-linear tipping point of total exhaustion."
                        )
                    },
                    {
                        "id": "B1",
                        "type": "Balancing Loop (Stabilizing Mechanism)",
                        "name": "BurnoutIQ Proactive Resilience Loop",
                        "color": "#00bfa5",
                        "dynamics": "Self-Correcting Negative Feedback (-)",
                        "nodes": [
                            {"order": 1, "name": "Workload Intensity Creep", "effect": "detected early by BurnoutIQ"},
                            {"order": 2, "name": "Early Telemetry Alert & Risk Flag", "effect": "notifies authorized manager"},
                            {"order": 3, "name": "Workload Redistribution & Meeting Detox", "effect": "reduces weekly load"},
                            {"order": 4, "name": "Restored Rest Boundary & Recovery Window", "effect": "restores sleep & capacity"},
                            {"order": 5, "name": "Recharged Cognitive Throughput", "effect": "restores execution speed"},
                            {"order": 6, "name": "Sustainable Delivery Velocity", "effect": "stabilizes Workload Pressure (-)"}
                        ],
                        "systemic_benefit": (
                            "Intervenes *upstream* at Node 1 before fatigue compounds into missed deadlines and emotional depletion."
                        )
                    }
                ],
                "delays_and_tipping_points": [
                    {
                        "phenomenon": "The Fatigue-Latency Trap",
                        "explanation": "Physiological and psychological exhaustion lags overtime hours by 3 to 6 weeks. By the time an employee self-reports burnout, they have already sustained significant cognitive depletion."
                    },
                    {
                        "phenomenon": "The Crisis Over-Correction",
                        "explanation": "Organizations that wait for project failure often panic and enforce sudden hiring freezes or sudden reorganizations, which perversely accelerates work pressure on remaining staff."
                    }
                ]
            },
            {
                "id": "model_trust_reliability",
                "number": 4,
                "title": "Model Trust & Reliability Framework",
                "subtitle": "The 6 Foundational Pillars of Responsible and Methodologically Sound Enterprise ML",
                "archetype": "Multi-Tiered Architectural Integrity Stack",
                "visual_type": "stack",
                "visual_asset_url": "/frameworks/04_model_trust_reliability.jpg",
                "core_principle": (
                    "Enterprise HR AI cannot rely on 'black box' claims. Building true model trust demands verifiable data provenance, "
                    "zero-leakage validation splits, baseline benchmarking, calibrated probability estimates, empirical uncertainty quantification, "
                    "and strict human-in-the-loop ethical boundaries."
                ),
                "tiers": [
                    {
                        "tier": 1,
                        "name": "Empirical Data Quality & Provenance",
                        "color": "#1565c0",
                        "standard": "Provenance Segregation",
                        "description": (
                            "Strict boundary between real-world empirical research datasets (1,598 academic librarian CBI responses, "
                            "Cronbach's α = 0.887) and synthetic enterprise telemetry simulations (150k employee records). "
                            "Automated sanitization strips all direct identifiers (names, emails, phone numbers) before ingestion."
                        )
                    },
                    {
                        "tier": 2,
                        "name": "Zero-Leakage Architecture",
                        "color": "#0097a7",
                        "standard": "Subject-Grouped Splitting",
                        "description": (
                            "In longitudinal modeling, splits are grouped strictly on `employee_id`. Zero observations from the same individual "
                            "appear in both training and test folds. Direct psychometric survey items (cbi_w1–cbi_w7) are strictly excluded from "
                            "predictive features to prevent target-proxy leakage."
                        )
                    },
                    {
                        "tier": 3,
                        "name": "Persistence Baseline Benchmarking",
                        "color": "#fbc02d",
                        "standard": "Beating Naive Baselines",
                        "description": (
                            "Every predictive model must justify its deployment by outperforming naive baselines. "
                            "The production Ridge longitudinal regressor achieves RMSE 10.19, beating the gold-standard Persistence Baseline "
                            "(ŷ_{t+1} = y_t, RMSE 11.21) by -1.0266 RMSE (-9.15% error reduction) and naive mean (RMSE 17.22)."
                        )
                    },
                    {
                        "tier": 4,
                        "name": "Probability Calibration & Score Bounding",
                        "color": "#43a047",
                        "standard": "Brier Score < 0.06",
                        "description": (
                            "Classification algorithms are wrapped in CalibratedClassifierCV using 5-fold cross-validation and sigmoid scaling. "
                            "Ensures that an employee flagged with a '70% probability of elevated risk' actually belongs to a cohort where "
                            "7 out of 10 experience elevated burnout (Brier score 0.0512; ROC-AUC 0.9501)."
                        )
                    },
                    {
                        "tier": 5,
                        "name": "Empirical Uncertainty Intervals",
                        "color": "#0288d1",
                        "standard": "±1.96 s_e Empirical Coverage",
                        "description": (
                            "Predictions are never presented as single pseudo-precise numbers. Every score includes empirical error bounds: "
                            "±0.56 pts for 0–10 score regression, and ±19.63 CBI pts (94.8% test coverage) for longitudinal forecasting."
                        )
                    },
                    {
                        "tier": 6,
                        "name": "Human-in-the-Loop Governance & Non-Causal Boundaries",
                        "color": "#7b1fa2",
                        "standard": "Ethical HR Guardrail",
                        "description": (
                            "Predictions are strictly decision-support aids for supportive accommodations. Prohibits fully automated "
                            "personnel decisions, terminations, or compensation indexing. Emphasizes that correlations reflect telemetry patterns, "
                            "not causal physiological claims."
                        )
                    }
                ]
            },
            {
                "id": "intervention_to_impact",
                "number": 5,
                "title": "Intervention-to-Impact Framework",
                "subtitle": "The 6-Stage Outcome Ledger & Denominator Accountability Funnel",
                "archetype": "Measurement Ledger & Denominator Funnel",
                "visual_type": "funnel",
                "visual_asset_url": "/frameworks/05_intervention_to_impact.jpg",
                "core_principle": (
                    "Corporate wellness initiatives frequently claim 'success' through selective sampling and denominator manipulation "
                    "(e.g., claiming 80% improvement by ignoring the 90% of employees who dropped out). BurnoutIQ enforces strict "
                    "denominator accountability across a 6-stage outcome ledger."
                ),
                "funnel_stages": [
                    {
                        "step": 1,
                        "name": "Baseline Assessment (t_0)",
                        "denominator_rule": "Total Monitored Cohort (N = 1,046 in longitudinal trial)",
                        "metric_label": "Baseline Risk Population",
                        "metric_value": "1,046 Employees",
                        "description": "Initial measurement establishing pre-intervention CBI score, telemetry friction, and risk tier."
                    },
                    {
                        "step": 2,
                        "name": "Supportive Action Logging",
                        "denominator_rule": "Identified Eligible Cases (927 flagged cases)",
                        "metric_label": "Intervention Intake Rate",
                        "metric_value": "927 Cases Initiated (88.6% of flagged)",
                        "description": "Structured assignment of workload caps, meeting detox, or coaching logged into immutable action ledger."
                    },
                    {
                        "step": 3,
                        "name": "Implementation Window",
                        "denominator_rule": "Minimum 30-Day Accommodation Duration",
                        "metric_label": "Active Implementation Period",
                        "metric_value": "30 to 60 Days",
                        "description": "Standardized observation window ensuring accommodations have sufficient latency to affect recovery."
                    },
                    {
                        "step": 4,
                        "name": "Follow-Up Assessment (t_1)",
                        "denominator_rule": "Completed vs. Dropped Out",
                        "metric_label": "Survey Reassessment Coverage",
                        "metric_value": "574 / 1,046 Evaluated (54.9%)",
                        "description": "Subsequent survey wave administered to measure actual score change without cherry-picking respondents."
                    },
                    {
                        "step": 5,
                        "name": "Observed Score Delta Calculation",
                        "denominator_rule": "Evaluated Population (N = 574)",
                        "metric_label": "Mean Observed Change",
                        "metric_value": "-8.4 CBI Points (SD: 6.2)",
                        "description": "Calculates individual Δ = Score_{t_1} - Score_{t_0}. Categorizes cases into Improved, Stable, or Worsened."
                    },
                    {
                        "step": 6,
                        "name": "Denominator Accountability & Impact Synthesis",
                        "denominator_rule": "Complete Funnel Transparency",
                        "metric_label": "Verified Recovery Rate",
                        "metric_value": "311 Improved / 574 Surveyed (54.2%)",
                        "description": (
                            "Reports 451 completed / 927 total cases (48.7% completion). Highlights that 311 showed sustained reduction, "
                            "182 remained stable, and 81 worsened despite intervention. Causal disclaimer explicitly attached."
                        )
                    }
                ],
                "crucial_distinction": {
                    "observational_evidence": "Demonstrates statistical correlation between supportive guardrails and subsequent score reduction across waves.",
                    "causal_evidence": "Requires a randomized controlled trial (RCT) with counterfactual controls to definitively prove the intervention caused the reduction.",
                    "burnoutiq_standard": "Always reports findings as 'observed associations', strictly avoiding fabricated causal claims."
                }
            }
        ]
    }
