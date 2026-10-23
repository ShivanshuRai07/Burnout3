# BurnoutIQ / WorkPulse AI — Complete Project Context & Architecture Guide

> **Document Type:** Master System Context, Engineering Architecture, and Operational Reference  
> **Repository:** `SB_Miniproject_Kartik` (Corpus: `ShivanshuRai07/Burnout`)  
> **Core Value Proposition (USP):** `PREDICT → INTERVENE → VERIFY OUTCOMES`  
> **Active Verification:** 75 Automated Tests Passing (`pytest-9.0.2`, Python 3.14.3)  
> **Local Server:** `http://127.0.0.1:8501/`

---

## 1. Executive Summary & Vision

**BurnoutIQ** (formerly WorkPulse AI) is an enterprise occupational health analytics and workload-balancing decision-support platform. Unlike traditional reactive HR surveys that measure burnout only after employees reach acute exhaustion, BurnoutIQ provides a **closed-loop cybernetic prevention system**:

```
[ 1. PREDICT ] ──► [ 2. TRIAGE ] ──► [ 3. INTERVENE ] ──► [ 4. VERIFY ] ──► [ 5. LEARN ]
Autoregressive     Telemetry-Driven  Logged Supportive    Longitudinal       Organizational
Time-Series        Friction          Accommodations       Wave Scoring       Playbook
Forecasting        Decomposition     (Meeting/Hours)      (Δ Score)          Optimization
```

### Core Problems Solved
1. **The Wellness Parameter Trap**: Most corporate wellness initiatives spend 90% of their budgets on surface symptoms (meditation apps, gym discounts, pizza parties) without touching structural workload drivers (excessive meetings, overtime creep, bottleneck dependencies).
2. **Open-Loop Telemetry**: Typical HR analytics generate scores or risk dashboards but completely disconnect from intervention execution and follow-up outcome measurement.
3. **Pseudoscience & Data Leakage**: Predictive HR models frequently suffer from target leakage, uncalibrated probabilities, and fabricated claims of causality. BurnoutIQ enforces zero-leakage grouped splitting, baseline benchmarking against persistence models, probability calibration, and strict non-causal observational boundaries.

---

## 2. Machine Learning Architecture & Operational Tasks

BurnoutIQ clearly delineates three distinct machine learning tasks, preserving the critical mathematical boundary between continuous 0–10 scores, binary risk probabilities, and longitudinal CBI 0–100 indices:

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    BURNOUTIQ ML SUITE OVERVIEW                                    │
├───────────────────────────────┬───────────────────────────────────┬───────────────────────────────┤
│ Task A: Continuous Regression │ Task B: Risk Classification       │ Task C: CBI Forecasting       │
├───────────────────────────────┼───────────────────────────────────┼───────────────────────────────┤
│ Target: burnout_score [0–10]  │ Target: is_elevated_risk [0, 1]   │ Target: target_next_cbi [0–100│
│ Model: HistGradientBoosting   │ Model: CalibratedClassifierCV     │ Model: Autoregressive Ridge   │
│ Test MAE: 0.4226 | R²: 0.7442 │ ROC-AUC: 0.9501 | Brier: 0.0512   │ Test RMSE: 10.1883 | R²: 0.648│
│ Uncertainty: ±0.56 pts        │ Operating Threshold: τ = 0.33     │ vs Persistence: -1.0266 RMSE  │
└───────────────────────────────┴───────────────────────────────────┴───────────────────────────────┘
```

### Task A: Continuous Burnout Score Regression (0.0 – 10.0 Scale)
- **Target Variable:** `burnout_score` (Continuous scale $[0.0, 10.0]$; mean $2.11$, SD $1.11$).
- **Dataset Source:** Tech Mental Health Workforce (`150,000` synthetic enterprise telemetry records).
- **Split Strategy:** 80% Train (`120,000`), 20% Held-Out Test (`30,000`), internal 20% validation tuning.
- **Production Model:** `HistGradientBoostingRegressor(learning_rate=0.07, max_iter=200, max_leaf_nodes=31)` wrapped in a scikit-learn Pipeline with median imputation, standard scaling, and one-hot encoding.
- **Empirical Benchmarks:**
  | Model | Val RMSE | Val MAE | Val R² | Test RMSE | Test MAE | Test R² | Status |
  | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
  | **HistGradientBoostingRegressor** | **0.5603** | **0.4196** | **0.7441** | **0.5634** | **0.4226** | **0.7442** | **Production Winner** |
  | RandomForestRegressor (100 trees) | 0.5761 | 0.4306 | 0.7295 | 0.5761 | 0.4317 | 0.7326 | Evaluated |
  | Ridge Regression (L2 α=1.0) | 0.6181 | 0.4928 | 0.6886 | 0.6227 | 0.4953 | 0.6876 | Evaluated |
  | Naive Mean Baseline ($\hat{y}=\bar{y}$) | 1.1078 | 0.9215 | -0.0001 | 1.1140 | 0.9253 | -0.0000 | Benchmark Baseline |
- **Residual Distribution:** Mean error `+0.0012`, standard error $s_e = 0.5634$. Empirical 68% interval $\pm0.56$, 95% interval $\pm1.10$ pts.
- **Artifact:** [`artifacts/burnout_score_model.joblib`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/burnout_score_model.joblib)

### Task B: Elevated-Risk Classification & Probability Calibration
- **Target Variable:** `is_elevated_risk` (Binary classification at $\tau = 3.70$, the 90th percentile of baseline burnout scores; 10.4% positive prevalence).
- **Calibration Engine:** `CalibratedClassifierCV(cv=5, method='sigmoid')` wrapping `HistGradientBoostingClassifier`.
- **Operational Decision Threshold:** $\tau = 0.33$ calibrated probability (selected via Youden's $J$ and cost-sensitive F1 optimization).
- **Empirical Benchmarks:**
  | Model | ROC-AUC | PR-AUC | Brier Score | Tuned F1 | Tuned Precision | Tuned Recall | Status |
  | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
  | **HistGradientBoosting + Calibrated** | **0.9501** | **0.7319** | **0.0512** | **0.6648** | **0.6269** | **0.7075** | **Production Winner** |
  | Logistic Regression (L2) | 0.9524 | 0.7391 | 0.0505 | 0.6685 | 0.6283 | 0.7141 | Candidate |
  | Random Forest Classifier | 0.9445 | 0.7113 | 0.0545 | 0.6499 | 0.6104 | 0.6947 | Evaluated |
  | Majority Class Baseline | 0.5000 | 0.1101 | 0.1101 | 0.0000 | 0.0000 | 0.0000 | Baseline |
- **Empirical Confusion Matrix at $\tau = 0.33$:**
  - True Positives: `2,211` | False Positives: `1,314`
  - False Negatives: `914` | True Negatives: `25,561`
  - Sensitivity (Recall): `70.75%` | Specificity: `95.11%` | Overall Accuracy: `92.57%`
- **Artifact:** [`artifacts/elevated_risk_model.joblib`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/elevated_risk_model.joblib)

### Task C: Copenhagen Burnout Inventory (CBI) Longitudinal Forecasting
- **Target Variable:** `target_next_cbi_work_score` (Continuous $[0.0, 100.0]$ Copenhagen Burnout Inventory Work-Related Subscale at month $t+1$).
- **Dataset Source:** Longitudinal Panel (`11,764` sequential records across `2,065` synthetic employees over 12 monthly waves).
- **Split Strategy:** Grouped split on `employee_id` (1,652 train employees, 413 test employees). **Strict zero employee overlap between train and test sets.**
- **Features Used:** Historical score at period $t$, moving average trends, work hours, overtime, meetings per day, deadline friction, and workload interaction features. Direct survey items (`cbi_w1`–`cbi_w7`) are **strictly excluded** from features to prevent leakage.
- **Empirical Benchmarks vs. Persistence Baseline:**
  | Model | Test RMSE | Test MAE | Test R² | vs. Persistence Baseline ($\Delta$ RMSE) | Status |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | **Ridge Multi-Feature Regressor** | **10.1883** | **8.0491** | **0.6480** | **-1.0266 RMSE (-9.15% error reduction)** | **Production Winner** |
  | HistGradientBoostingRegressor | 10.4128 | 8.2566 | 0.6323 | -0.8021 RMSE | Evaluated |
  | RandomForestRegressor | 10.4444 | 8.2771 | 0.6301 | -0.7705 RMSE | Evaluated |
  | **Gold-Standard Persistence ($\hat{y}_{t+1}=y_t$)** | **11.2149** | **8.7615** | **0.5735** | **0.0000 (Gold Standard Baseline)** | Benchmark Baseline |
  | Naive Mean Baseline ($\hat{y}_{t+1}=\bar{y}$) | 17.2166 | 13.8457 | -0.0051 | +6.0017 RMSE | Naive Baseline |
- **Prediction Uncertainty:** Residual standard error $s_e = 10.02$. Empirical 95% prediction interval is $\pm19.63$ CBI points ($1.96 \times s_e$), verified with **94.8% empirical test coverage**.
- **Artifact:** [`artifacts/forecast_model.joblib`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/forecast_model.joblib) & [`artifacts/forecast_metrics.json`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/forecast_metrics.json)

---

## 3. Dataset Provenance & Separation Architecture

BurnoutIQ maintains strict scientific isolation between operational telemetry, research datasets, and external competition benchmarks:

```text
Datasets/
├── burnoutiq_dataset/data/
│   ├── employee_profiles.csv             # 2,065 employees demographic and baseline attributes
│   ├── monthly_employee_panel.csv        # 24,780 monthly panel records across 12 waves
│   ├── interventions.csv                 # 927 recorded supportive interventions
│   ├── intervention_outcomes_view.csv    # Merged baseline -> action -> follow-up view
│   └── forecast_t_to_t1.csv              # 11,764 transition pairs for autoregressive forecasting
├── raw/
│   ├── tech_mental_health_burnout.csv    # 150,000 synthetic enterprise telemetry records
│   ├── hacker_earth_burnout.csv          # 12,180 synthetic competition benchmark records
│   └── academic_librarian_cbi_dataset.csv# 1,598 real-world empirical survey responses (Kennesaw State DigitalCommons)
└── master_workforce_dataset.pkl.gz       # 178,750 combined baseline workforce records
```

### Dataset Provenance Details
1. **Tech Mental Health Workforce (`150,000` records)**: Synthetic enterprise telemetry simulation modeling work patterns, meeting loads, overtime, and self-reported stress. Used for training and benchmarking Task A and Task B.
2. **Longitudinal Panel Simulation (`11,764` transitions across `2,065` employees)**: Multi-wave panel tracking dated monthly assessments and intervention lifecycles. Used for autoregressive CBI forecasting (Task C).
3. **Academic Librarian CBI Dataset (`1,598` records)**: Real-world empirical survey responses from a Kennesaw State University study (Wood et al., DigitalCommons) evaluating the Copenhagen Burnout Inventory. Evaluated in [load_real_cbi.py](file:///d:/Kartik/SB_Miniproject_Kartik/load_real_cbi.py) to establish psychometric reliability (Cronbach's $\alpha = 0.887$, reverse-scored Item 7). **Strictly excluded from commercial training to prevent domain pollution.**
4. **HackerEarth Burnout Dataset (`12,180` records)**: Independent synthetic competition dataset kept in isolation as an external cross-benchmark.

---

## 4. Frontend & User Interface Architecture

The enterprise dashboard ([dashboard.html](file:///d:/Kartik/SB_Miniproject_Kartik/dashboard.html)) is an ultra-clean, vanilla HTML5/CSS3/JavaScript single-page application (zero external framework bloat) organized into seven dedicated, modular views:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                            BURNOUTIQ TOP NAVIGATION BAR                                          │
├────────────────────┬──────────────────┬─────────────────┬─────────────────┬───────────┬─────────────┬────────────┤
│ 🛡 Prevention      │ ⚡ Scenario      │ 👥 Employee     │ 📊 Role &       │ 🧪 Model  │ 🧭 Frame-   │ 📁 File    │
│    Workflow (Hero) │    Simulator     │    Directory    │    Telemetry    │    Lab    │    works    │    Upload  │
└────────────────────┴──────────────────┴─────────────────┴─────────────────┴───────────┴─────────────┴────────────┘
```

### View 1: 🛡 Prevention Workflow (`#sec-prevention`) — Primary Hero View
Organized around the core USP: **PREDICT → INTERVENE → VERIFY OUTCOMES**.
- **Stage A: Executive Prevention Trajectory Brief**:
  - *What Is Worsening:* Identifies that 24.3% of the monitored workforce is experiencing friction, with +4.8% net escalation across 180 teams.
  - *Observed Change Magnitude:* Mean monthly CBI delta is +3.1 pts (SD: 4.8) for unmitigated cohorts vs. -8.4 pts for accommodated teams.
  - *Why (Telemetry Drivers):* Isolates meeting density (>4.2 hrs/day) and overtime (>12 hrs/wk) as explaining 82% of elevated transitions.
  - *Evidence & Boundaries:* Discloses zero-leakage grouped split metrics ($s_e = 10.02$, $\pm19.63$ CBI interval). Non-diagnostic.
- **Stage B: Prioritized Attention Queue & Actionable Cohort Triage**:
  - *Critical Escalation Queue (CBI $\ge 65$):* 142 cases requiring immediate review, meeting detox, and 1:1 check-ins.
  - *Follow-up Reassessment Due:* 89 cases where a supportive intervention was logged >30 days ago and wave-2 follow-up survey is due.
  - *Observed Improvement Cohort:* 311 cases demonstrating sustained score reductions >5 CBI points.
  - *Direct 1-Click Inspection:* Instant modal links to cases like `SYN-00048`, `SYN-00388`, and `SYN-00017`.
- **Stage C: Executive Impact & Verification Summary (Explicit Denominators)**:
  - *Intervention Completion Rate:* `48.7%` ($451 / 927$ total initiated cases).
  - *Survey Reassessment Coverage:* `54.9%` ($574 / 1,046$ total cohort).
  - *Verified Improvement Rate:* `54.2%` ($311 / 574$ surveyed cases).
  - *Mean Observed Score Change:* `-8.4 CBI points` (among employees with completed supportive accommodations).

### View 2: ⚡ Scenario Simulator (`#sec-simulator`)
- Interactive what-if counterfactual sandbox with sliders for Overtime Hours ($0–20$h), Meetings per Day ($0–10$), Work Hours per Week ($20–80$h), Stress Level ($1–10$), Sleep Hours ($3–12$h), Job Satisfaction, and Role.
- Real-time client-side and server-side prediction recalculation, estimating the impact of organizational policy guardrails (e.g. "Focus Fridays", overtime caps).

### View 3: 👥 Employee Directory (`#sec-employees`)
- **Zero-Blank-Screen Categorization**: Automatically populates 181,039 records across 5 cohort categories with live count badges:
  - 🚨 **Elevated Risk** (`33,912` employees flagged above threshold)
  - 🎯 **Active Interventions Tracked** (`768` ongoing supportive accommodations)
  - 📈 **Longitudinal Panel** (`2,289` employees with multi-wave survey tracking)
  - ⚠️ **High Workload Friction** (`139,108` employees experiencing meeting overload or overtime)
  - 👥 **All Monitored Workforce** (`181,039` total records)
- **Pre-Loaded Priority Inspection**: Automatically pre-populates the Longitudinal Inspector with featured case `SYN-00017` (12 assessment waves, active coaching, -13.0 CBI score delta) upon tab navigation.
- **Quick-Inspect Chips**: One-click inspector buttons for `SYN-00017`, `SYN-00048`, `SYN-00388`, `tech_1`, and `tech_4`.
- **Full Operational Filtering**: Manual ID search, Role filter, Mode filter, and CSV Export.

### View 4: 📊 Role & Telemetry Analytics (`#sec-analytics`)
- Aggregated burnout distributions and friction metrics across job roles, remote/hybrid/onsite arrangements, and office locations.
- Policy leverage simulations showing projected workforce score reductions under standardized organizational guardrails.

### View 5: 🧪 Model Lab (`#sec-modellab`)
- Diagnostic laboratory completely separated from the decision-oriented Prevention Workflow.
- Interactive Task Selector: Task A (0–10 Regression), Task B (Calibrated Classification), Task C (CBI Forecasting).
- Dynamic Model Overview Grid, Empirical Model Performance Ranking Table, Actual vs. Predicted curves, Residual Error Distribution with empirical confidence bounds, Baseline Benchmark Lift charts, 4-Cell Confusion Matrix at $\tau = 0.33$, Feature Gain Importance chart, Dataset Insights table, and 6 Methodological Safeguard cards.

### View 6: 🧭 Systems-Thinking Frameworks (`#sec-frameworks`)
- 5 original conceptual frameworks inspired by Donella Meadows' *Leverage Points* and Simon Fraser University's *Intervention Level Framework (ILF)*.
- Features high-resolution vector infographic artwork (`artifacts/frameworks/`), interactive SVG/HTML diagrams, full-screen lightbox modal, layer breakdown accordions, systems dynamics leverage analysis, and non-causal boundaries.

### View 7: 📁 File Upload & Sanitization (`#sec-upload`)
- Enterprise CSV ingestion with local privacy streaming in 100,000-row chunks.
- Automated PII stripping, $k$-anonymity cell suppression ($k \ge 5$), local scoring, and in-memory aggregation.

---

## 5. The 5 Systems-Thinking Frameworks

```
                  ▲   DEEPEST LEVERAGE (Transformational Impact)
                 / \  Level 1: Cultural Mindset & Mental Models (Psychological Safety)
                /---\ 
               /     \ Level 2: System Goals & Policies (Overtime Caps, Rest Boundaries)
              /-------\
             /         \ Level 3: Team Structure & Topology (Load Rebalancing, Buffers)
            /-----------\
           /             \ Level 4: Feedback Loops & Telemetry (BurnoutIQ Early Detection)
          /---------------\
         /                 \ Level 5: Daily Work Conditions & Events (Meeting Spikes, Apps)
        --------------------- LOWEST LEVERAGE (Transient Parameter Tweaks)
```

1. **Burnout Prevention Leverage Framework (5-Tier Pyramid)**:
   - *Level 1 (Apex):* Cultural Paradigm & Mental Models (Psychological safety vs. hero overwork).
   - *Level 2:* System Goals & Institutional Rules (45h overtime caps, Focus Fridays, protected rest).
   - *Level 3:* Team Structure & Work Distribution (Load balancing, peer pairing, cross-training).
   - *Level 4:* Feedback Loops & Early Telemetry (BurnoutIQ detection: hours, overtime, meetings).
   - *Level 5 (Base):* Daily Work Conditions & Events (Slack pings, wellness seminars, meditation apps).
   - *Asset:* [`01_burnout_prevention_leverage.jpg`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/frameworks/01_burnout_prevention_leverage.jpg)

2. **Predict → Intervene → Verify Framework (Cybernetic Loop)**:
   - 5-stage unbroken closed-loop cycle: 1. Predictive Forecasting ($t \to t+1$) $\to$ 2. Evidence Interpretation & Triage $\to$ 3. Supportive Intervention Logging $\to$ 4. Longitudinal Verification ($\Delta$ Score) $\to$ 5. Continuous Learning & Playbook Recalibration.
   - *Asset:* [`02_predict_intervene_verify.jpg`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/frameworks/02_predict_intervene_verify.jpg)

3. **Workplace Burnout Feedback Loop Framework (Causal Loop Diagram - CLD)**:
   - *Reinforcing Loop R1 (The Overwork Spiral):* Pressure $\xrightarrow{+}$ Overtime/Meetings $\xrightarrow{+}$ Fatigue $\xrightarrow{+}$ Cognitive Friction $\xrightarrow{+}$ Missed Deadlines $\xrightarrow{+}$ Pressure.
   - *Balancing Loop B1 (BurnoutIQ Proactive Resilience):* Telemetry Spike $\xrightarrow{+}$ Early Alert $\xrightarrow{+}$ Workload Reallocation $\xrightarrow{-}$ Restored Rest Boundary $\xrightarrow{-}$ Sustainable Velocity.
   - *Fatigue-Latency Trap:* Biological fatigue lags overtime hours by 3–6 weeks; early telemetry detects friction before the cognitive tipping point.
   - *Asset:* [`03_workplace_burnout_feedback_loops.jpg`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/frameworks/03_workplace_burnout_feedback_loops.jpg)

4. **Model Trust & Reliability Framework (6 Foundational Pillars)**:
   - *Tier 1 (Base):* Empirical Data Provenance (Separation of real CBI vs synthetic telemetry).
   - *Tier 2:* Zero-Leakage Architecture (Grouped split on `employee_id`, survey items masked).
   - *Tier 3:* Persistence Baseline Benchmark (Ridge beats persistence by -1.03 RMSE).
   - *Tier 4:* Probability Calibration (CalibratedClassifierCV, Brier 0.0512).
   - *Tier 5:* Uncertainty Quantification ($\pm1.96 s_e$ prediction intervals).
   - *Tier 6 (Apex):* Ethical Non-Causal Governance (Decision support only, strictly non-punitive).
   - *Asset:* [`04_model_trust_reliability.jpg`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/frameworks/04_model_trust_reliability.jpg)

5. **Intervention-to-Impact Framework (Outcome Ledger & Denominator Funnel)**:
   - 6-stage measurement ledger with explicit denominators: Baseline Population ($1,046$) $\to$ Initiated ($927$, 88.6%) $\to$ Completed ($451$, 48.7%) $\to$ Follow-up Reassessment ($574$, 54.9%) $\to$ Verified Improvement ($311$, 54.2% of surveyed) $\to$ Mean Delta ($-8.4$ CBI points).
   - *Asset:* [`05_intervention_to_impact.jpg`](file:///d:/Kartik/SB_Miniproject_Kartik/artifacts/frameworks/05_intervention_to_impact.jpg)

---

## 6. Backend API Specifications & Routes

The backend is implemented with dual-server compatibility:
- **Local Standalone Server:** [dashboard_server.py](file:///d:/Kartik/SB_Miniproject_Kartik/dashboard_server.py) (`http.server.ThreadingHTTPServer` on port 8501).
- **Serverless Cloud Server:** [api/index.py](file:///d:/Kartik/SB_Miniproject_Kartik/api/index.py) (Flask WSGI handler for Vercel/cloud deployments).

### REST API Endpoints Reference
| HTTP Method | Endpoint | Description | Key Parameters / Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/` or `/index.html` | Serves main single-page web dashboard | None |
| `GET` | `/api/health` | Service health, version, loaded records, and model status | None |
| `GET` | `/api/summary` | Active dataset metadata, risk distribution, and role analytics | None |
| `GET` | `/api/forecast` | Time-series forecasting metrics, monthly points, and projections | `?cohort=<CohortName>` |
| `GET` | `/api/interventions-tracking` | Funnel metrics, dual-track lifecycles, and observed improvement counts | None |
| `GET` | `/api/interventions/records` | Paginated, filterable action records from persistent store | `?status=&dept=&search=&sort_by=&page=&page_size=` |
| `POST` | `/api/interventions/record` | Log a newly assigned supportive intervention | `{"employee_id", "intervention_type", "owner", ...}` |
| `POST` | `/api/interventions/update-status`| Update intervention status, owner, or notes | `{"action_id", "status", "owner", "notes", ...}` |
| `POST` | `/api/interventions/record-followup`| Record wave-2 assessment score and update trajectory | `{"action_id", "follow_up_cbi_score", "notes", ...}` |
| `GET` | `/api/model-lab` | Complete Model Lab metrics for Task A, B, C, benchmarks, and datasets | None |
| `GET` | `/api/frameworks` | Complete JSON for 5 systems-thinking frameworks and layer breakdowns | None |
| `GET` | `/frameworks/<filename>` | Serves high-resolution framework infographic images | Image filename (e.g. `01_burnout_prevention_leverage.jpg`) |
| `GET` | `/api/featured-employee` | Pre-loaded priority employee profile (`SYN-00017`) for zero-blank-screen | None |
| `GET` | `/api/search-employee` | Search individual employee profile and longitudinal timeline | `?id=<EmployeeID>` |
| `GET` | `/api/employee-table` | Paginated workforce table with category filtering and CSV export | `?category=&include_master=&search=&filter_role=&page=` |
| `POST` | `/api/predict` | Single-employee feature scoring and workplace indicator flags | `{"work_hours_per_week", "overtime_hours", ...}` |
| `POST` | `/api/analyse-upload` | Privacy-sanitized CSV upload streaming and local batch scoring | Multipart form-data with `file` |
| `POST` | `/api/reset-dataset` | Resets dashboard state back to Master Unified Workforce Dataset | None |

---

## 7. Automated Test Suite & Verification Matrix

All 75 tests pass cleanly in under 30 seconds (`pytest-9.0.2`, Python 3.14.3):

```bash
python -m pytest -v
============================= 75 passed in 26.64s =============================
```

### Test Suite Directory Structure
| Test Suite File | Tests | Coverage Scope |
| :--- | :--- | :--- |
| [`tests/test_cbi_loader.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_cbi_loader.py) | 7 | Real-world CBI survey loader, Item 7 reverse scoring, Cronbach's $\alpha = 0.887$, and sample discrepancy auditing. |
| [`tests/test_dashboard_regression.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_dashboard_regression.py) | 8 | DashboardState initialization, summary, prediction, empty upload table invariant, and Flask/Vercel parity. |
| [`tests/test_model_pipeline.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_model_pipeline.py) | 6 | Scikit-learn Pipeline preprocessing, regression benchmarking, classification threshold tuning, CalibratedClassifierCV, and grouped forecasting split without person leakage. |
| [`tests/test_phase3_integration.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_phase3_integration.py) | 17 | Model artifacts loading, feature schemas, known low/moderate/elevated scenarios, bounds validation, and slider scale mappings. |
| [`tests/test_phase4_responsible_use.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_phase4_responsible_use.py) | 16 | Workplace indicators, non-medical suggestions, PII stripping, ID masking, $k$-anonymity cell suppression ($k \ge 5$), and pilot governance. |
| [`tests/test_targeted_dashboard_improvements.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_targeted_dashboard_improvements.py) | 6 | Time-series forecasting structure, intervention funnels, active dataset context switching, and upload isolation. |
| [`tests/test_usp_workflow.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_usp_workflow.py) | 5 | Empirical 95% prediction intervals, cohort filtering, action store disk persistence, and follow-up outcome scoring. |
| [`tests/test_model_lab_and_categories.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_model_lab_and_categories.py) | 3 | Dedicated `/api/model-lab` payload, employee directory category filters (`elevated`, `interventions`, `longitudinal`, `workload`, `all`), and featured employee auto-population. |
| [`tests/test_frameworks.py`](file:///d:/Kartik/SB_Miniproject_Kartik/tests/test_frameworks.py) | 7 | Systems-thinking `/api/frameworks` API, all 5 framework schemas (pyramid, cycle, CLD, stack, funnel), and high-resolution image serving. |

---

## 8. Responsible AI, Privacy & Ethical Governance

> [!IMPORTANT]
> **Non-Diagnostic Decision-Support Standard**:  
> BurnoutIQ outputs represent statistical estimations of workplace friction. They are **never** medical, psychiatric, or psychological diagnoses.

### Strict Governance Rules
1. **Adverse Employment Prohibitions**: Model predictions are strictly prohibited from being used for terminations, disciplinary actions, compensation indexing, or promotion gating.
2. **Human-in-the-Loop Mandate**: All algorithmic signals require human review by authorized People Operations or department leaders. Automated personnel decisions are strictly blocked.
3. **Automated PII Sanitization**: Direct identifiers (names, personal emails, phone numbers, government IDs, salary, medical notes) are automatically stripped prior to computation or storage.
4. **$k$-Anonymity Cell Suppression ($k \ge 5$)**: Any reporting cell or demographic breakdown representing fewer than 5 individuals is suppressed to prevent deanonymization.
5. **Observational vs. Causal Framing**: All before-and-after outcome comparisons are reported as **observed empirical associations**, strictly disclaiming causal proof without randomized counterfactual control trials.

---

## 9. Repository Quickstart & Commands

### Running the Dashboard Locally
```powershell
# Run the standalone HTTP server on port 8501
python dashboard_server.py --port 8501
```
Navigate to `http://127.0.0.1:8501/` in your browser.

### Running the Automated Test Suite
```powershell
# Run all 75 automated unit and integration tests
python -m pytest -v

# Run only the Systems-Thinking Frameworks tests
python -m pytest tests/test_frameworks.py -v

# Run only the Model Lab & Categories tests
python -m pytest tests/test_model_lab_and_categories.py -v
```

### Inspecting Real-World CBI Survey Loader
```powershell
# Run the psychometric CBI loader with Cronbach's alpha verification
python load_real_cbi.py --inspect
```

### Retraining Production Models
```powershell
# Execute the complete research and training pipeline
python train.py
```
