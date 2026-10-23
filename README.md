# BurnoutIQ / WorkPulse AI — Workforce Burnout Analytics Platform

BurnoutIQ is an occupational health analytics and workload-balancing decision-support prototype. It integrates validated numerical machine-learning models to help People Operations teams identify systemic fatigue indicators, evaluate workload interventions, and establish healthy operational guardrails.

---

## 0. The Model: the BurnoutIQ Loop (`burnoutiq/`)

The deliverable is one framework implemented as code: **Assess → Predict → Simulate → Intervene → Verify** for every employee each month, plus a quarterly **Learn** step. The dashboard only displays what the loop computes (`/api/loop`).

| Stage | File | What it does |
|---|---|---|
| Input | `burnoutiq/schema.py` | Three CSVs (`employees`, `monthly`, `interventions`), validated; templates in `templates/` |
| Assess | `burnoutiq/assess.py` | CBI work score 0–100 (item 7 reversed, ≥ 4 items); levels normal / high (≥ 50) / very high (≥ 65) |
| Predict | `burnoutiq/predict.py` | Next-month forecast, employee-level split, 95% range from held-out residuals; must beat "same as last month" |
| Simulate | `burnoutiq/simulate.py` | 500 simulated paths, 3 months ahead, with and without changes |
| Intervene | `burnoutiq/intervene.py` | Links each support action to baseline and follow-up scores; employee status in the loop |
| Verify | `burnoutiq/verify.py` | Improved (≤ −5) / no change / worsened (≥ +5); "reliable" only beyond the reliable change index |
| Flags | `burnoutiq/reference.py` | Absolute, division and personal reference points; individual vs systemic divisions; groups < 5 hidden |
| Learn | `burnoutiq/learn.py` | Each support type vs a matched comparison group; randomised pilot preferred; forecast calibration check |

```powershell
python -m burnoutiq --employees Datasets/burnoutiq_dataset/data/employees.csv --monthly Datasets/burnoutiq_dataset/data/assessments.csv --interventions Datasets/burnoutiq_dataset/data/interventions.csv --out reports/loop
python -m burnoutiq --templates templates
```

Results on the synthetic panel (latest month 2025-12): the forecast beats "same as last month" (MAE 7.99 vs 8.69) and its 95% range covers 95.4% of held-out cases. The matched comparison stays biased by confounding by indication: every support type looks 3–4 points closer to "no effect" than its known true effect. The randomised pilot recovers the true effect (−4.9, 95% CI −9.0 to −0.9; true −3.1), so only that estimate is used for simulation.

**Self-reported stress ablation** (`python train.py`, `reports/research/tables/self_report_ablation.md`): the 0–10 snapshot model's R² falls from 0.744 (all features) to 0.666 without `stress_level` and to 0.351 with workplace features only (AUC 0.95 → 0.83). Most of its accuracy comes from self-reports measured at the same time as the target.

Earlier material that the loop replaces is kept in `docs/archive/`: the five framework posters and old code, and the two training scripts that needed data not in this repo.

---

## 1. Validated Machine Learning Models

The platform integrates two production-validated tabular ML pipelines trained and benchmarked natively in scikit-learn on a standardized 150,000-record synthetic workforce benchmark:

1. **Continuous Burnout Score Regressor**:
   - **Model**: `HistGradientBoostingRegressor` (`learning_rate=0.07`, `max_iter=200`, `max_leaf_nodes=31`)
   - **Features**: 14 measured numeric columns + 3 categorical (no hand-weighted composite indexes).
   - **Benchmark**: Test RMSE: `0.5629`, Test $R^2$: `0.7447` (outperforms Mean Baseline RMSE `1.1140` and Ridge RMSE `0.6227`). With workplace data only (no self-reported wellbeing), $R^2$ falls to `0.351`; see Section 0.
   - **Output**: Continuous score on $[0.0, 10.0]$ with empirical estimation uncertainty bound ($\text{RMSE} \pm 0.56$).

2. **Calibrated Elevated-Risk Classifier**:
   - **Model**: `CalibratedClassifierCV(cv=5, method='sigmoid')` wrapping `HistGradientBoostingClassifier`.
   - **Benchmark**: Test ROC-AUC: `0.9501`, PR-AUC: `0.7309`, Brier Score: `0.0512` (logistic regression is marginally higher at 0.9524).
   - **Operational Threshold**: $\tau = 3.70$ (90th percentile of training score distribution; calibrated probability threshold $\tau \approx 33.0\%$).
   - **Output**: Calibrated probability $[0.0, 100.0]\%$ and categorical risk bands (`Low`, `Moderate`, `Elevated`).

---

## 2. Responsible Use & Ethical Safeguards

> [!IMPORTANT]
> **Decision-Support Prototype — Not a Medical Tool**: BurnoutIQ outputs are statistical estimations of occupational workload friction. They are **never** medical, psychiatric, or psychological diagnoses.

### Strict Governance Constraints
- **Prohibited Uses**: BurnoutIQ predictions must **never** be used for adverse employment decisions, including hiring, firing, disciplinary actions, performance penalties, salary reductions, or promotion denial.
- **Human-in-the-Loop**: Automated employment decisions are strictly prohibited. Algorithmic outputs serve solely as conversation starters for supportive managerial 1-on-1 check-ins.
- **Uncertainty Disclosure**: Individual predictions carry an expected error margin ($\text{RMSE} \pm 0.56$ points on a 0–10 scale). Scores must not be treated as indisputable ground truth.
- **Synthetic Benchmark Notice**: Production models are calibrated on synthetic enterprise telemetry. Real-world empirical generalization must be established locally before live operational reliance.

---

## 3. Actionable Workplace Insights & Suggestions

BurnoutIQ translates model outputs and telemetry into clear, non-medical operational suggestions:
- **Overtime Guardrails**: If overtime exceeds 4–6h/week, advises capping individual overtime at $\le 4$h/week to prevent cumulative exhaustion.
- **Meeting Detox**: If meetings exceed 4/day, recommends establishing focus blocks or meeting-free mornings. This is a rule-based hygiene suggestion only: meetings have zero permutation importance in the score model.
- **Workload Rebalancing**: If weekly hours exceed 48–50h, flags potential capacity deficits for task redistribution.
- **Milestone Rescoping**: If missed deadlines exceed 2, highlights timeline friction or unrealistic scoping for upcoming sprints.
- **Distinction of Tiers**: Every response explicitly separates `model_prediction`, `observed_telemetry`, and `suggested_actions`.

---

## 4. Privacy & Data Security Architecture

- **Automated PII Stripping**: Uploaded CSV files pass through an automated privacy filter that immediately detects and drops sensitive personal identifiers (names, emails, phones, SSNs, Aadhaar, salary, medical notes) prior to any computation or storage.
- **In-Memory Streaming**: Bulk CSV analysis streams data in 100,000-row chunks; uploaded files are processed in-memory and are not persisted to disk.
- **De-Identification & Cell Suppression ($k \ge 5$)**: Aggregate breakdown groups containing fewer than 5 employees are suppressed to prevent deanonymization. Individual search outputs mask employee identifiers (e.g. `tech_****`).
- **No Third-Party Transmission**: All inference occurs locally on internal compute; zero data is transmitted to external AI APIs or cloud vendors.
- **Legal Compliance Scope**: Formal compliance (GDPR, HIPAA, India DPDP Act) requires an independent organizational assessment before live deployment.

---

## 5. Controlled Pilot Plan

A comprehensive pilot deployment specification is documented in [PILOT_READINESS.md](PILOT_READINESS.md), including:
- Permissible stakeholder roles and authorized workflows.
- Minimum data telemetry requirements ($N=18$ features) and consent frameworks.
- In-situ calibration and demographic parity audits.
- Pilot KPIs (overtime reduction, meeting load hygiene, prediction calibration).
- Non-negotiable kill-switch triggers (misuse for performance penalties, model drift, privacy breaches).

---

## 6. Project Artifacts & File Structure

```text
├── artifacts/
│   ├── burnout_score_model.joblib      # Production continuous regressor pipeline
│   ├── elevated_risk_model.joblib       # Production calibrated classifier pipeline
│   ├── metrics.json                     # Phase 2 held-out benchmarks & operational threshold
│   └── master_workforce_dataset.pkl.gz  # Combined sources; models and dashboard use only the 150,000 tech rows
├── burnout_platform/
│   ├── features.py                      # Feature engineering (Workload Index, Wellness, Support)
│   ├── ingestion.py                     # Data ingestion and canonical schema staging
│   ├── insights.py                      # Workplace indicators and non-medical suggestions
│   ├── models.py                        # Model comparison, threshold tuning, and calibration
│   ├── privacy.py                       # PII stripping, cell suppression, and masking
│   └── validation.py                    # Input range validation and schema alignment
├── notebooks/
│   └── model_evaluation_proof.ipynb    # Google Colab research notebook (18/18 cells pass)
├── api/
│   └── index.py                         # Vercel serverless Flask backend
├── dashboard_server.py                  # Standalone local HTTP server
├── dashboard.html                       # Enterprise web analytics dashboard UI
├── load_real_cbi.py                     # Real-world CBI survey importer (empirical benchmark)
├── PILOT_READINESS.md                   # Controlled pilot governance and deployment plan
├── MODEL_REPORT.md                      # Model evaluation benchmarks and dataset provenance
└── tests/
    ├── test_cbi_loader.py               # CBI importer & Cronbach's alpha verification
    ├── test_dashboard_regression.py     # End-to-end dashboard backend regression suite
    ├── test_model_pipeline.py           # ML training, calibration, and forecasting tests
    ├── test_phase3_integration.py       # Model integration, known test cases & bounds
    └── test_phase4_responsible_use.py   # Insights, privacy, safeguards & pilot readiness
```

---

## 7. Setup & Testing

### Running the Local Dashboard
```powershell
python dashboard_server.py --port 8501
# Open http://127.0.0.1:8501 in your browser
```

### Running the Test Suite
```powershell
python -m pytest tests/ -v
```
All 94 tests verify the loop package, uploads, month-by-month runs, logged support, model accuracy, input boundaries, privacy safeguards, and API routes.
