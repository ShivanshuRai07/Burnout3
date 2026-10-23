# BurnoutIQ Model Evaluation and Selection Report

## Executive Summary

- **Primary Regressor Winner**: `hist_gradient_boosting` (RMSE: 0.5629, R²: 0.7447)
- **Primary Elevated-Risk Classifier**: `logistic_regression` with Platt/Sigmoid probability calibration (ROC-AUC: 0.9524, PR-AUC: 0.7391)
- **Operational Elevated-Risk Threshold**: Score ≥ **3.70** (training split 90th percentile)
- **Environment Compatibility**: Models fitted using current scikit-learn standard pipelines, resolving past `_loss` unpickler warnings and ensuring clean loading across local server and Vercel environments.

---

## 1. Domain 1: Enterprise Workforce Burnout Regression (0–10 scale)

- **Dataset**: 150,000 records from `tech_mental_health_burnout`
- **Splits**: 80% train (120,000), 20% unseen test (30,000); validation tuned on 20% internal train split
- **Target**: Continuous `burnout_score` (observed range: 1.0–8.1, mean: 2.11, SD: 1.11)
- **Excluded to Prevent Bias**: Age, gender, clinical therapy history, diagnostic mental health labels

| Regression Candidate | Val RMSE ↓ | Val MAE ↓ | Val R² ↑ | Test RMSE ↓ | Test MAE ↓ | Test R² ↑ | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| `mean_baseline` | 1.1078 | 0.9215 | -0.0001 | 1.1140 | 0.9253 | -0.0000 | Baseline |
| `ridge` | 0.6181 | 0.4928 | 0.6886 | 0.6227 | 0.4953 | 0.6876 | Evaluated |
| `random_forest` | 0.5773 | 0.4316 | 0.7283 | 0.5778 | 0.4330 | 0.7309 | Evaluated |
| `hist_gradient_boosting` | 0.5604 | 0.4191 | 0.7440 | 0.5629 | 0.4221 | 0.7447 | **Recommended Winner** |

---

## 2. Domain 1: Elevated-Risk Classification

- **Operational Target**: `burnout_score >= 3.70` (held-out positive rate: ~10.4%)
- **Threshold Selection**: Optimal threshold tuned on validation data maximizing F1

| Classifier Candidate | ROC-AUC ↑ | PR-AUC ↑ | Brier Score ↓ | F1 @ 0.50 | Optimal Val Thresh | F1 @ Tuned Thresh | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| `majority_baseline` | 0.5000 | 0.1101 | 0.1101 | 0.0000 | 0.10 | 0.0000 | Baseline |
| `logistic_regression` | 0.9524 | 0.7391 | 0.0505 | 0.6367 | 0.31 | 0.6693 | **Recommended Winner** |
| `random_forest` | 0.9446 | 0.7094 | 0.0550 | 0.5571 | 0.28 | 0.6451 | Evaluated |
| `hist_gradient_boosting` | 0.9501 | 0.7309 | 0.0512 | 0.6382 | 0.35 | 0.6627 | Evaluated |

---

## 3. Domain 2: Longitudinal Forecasting Benchmark (CBI 0–100 scale at month t+1)

- **Dataset**: `forecast_t_to_t1.csv` (11,764 observations across 2,065 employees)
- **Grouped Split**: Strictly partitioned by employee ID (no person-level leakage across time steps)
- **Gold-Standard Comparison**: Benchmarked against a Persistence Baseline (predicting next month = current month)

### Forecasting Regression (Target: CBI Score at t+1)

| Regressor | RMSE ↓ | MAE ↓ | R² ↑ | Notes |
|---|---:|---:|---:|---|
| `persistence_baseline` | 11.2149 | 8.7615 | 0.5735 | Gold-Standard Benchmark |
| `mean_baseline` | 17.2166 | 13.8457 | -0.0051 | Naive Baseline |
| `ridge` | 10.1883 | 8.0491 | 0.6480 | Multi-feature Regressor |
| `random_forest` | 10.4444 | 8.2771 | 0.6301 | Multi-feature Regressor |
| `hist_gradient_boosting` | 10.4128 | 8.2566 | 0.6323 | Multi-feature Regressor |

### Forecasting Risk Classification (Target: CBI ≥ 50 at t+1)

| Classifier | ROC-AUC ↑ | PR-AUC ↑ | F1 Score ↑ | Notes |
|---|---:|---:|---:|---|
| `persistence_baseline` | 0.9003 | 0.6457 | 0.6040 | Persistence Benchmark |
| `majority_baseline` | 0.5000 | 0.1593 | 0.0000 | Naive Baseline |
| `logistic_regression` | 0.9090 | 0.6851 | 0.5677 | Learned Classifier |
| `random_forest` | 0.9000 | 0.6580 | 0.5204 | Learned Classifier |
| `hist_gradient_boosting` | 0.8984 | 0.6558 | 0.5638 | Learned Classifier |

---

## 4. Leakage Prevention and Ethical Boundaries

1. **Grouped Employee Splitting**: In all longitudinal evaluations, splitting was conducted on employee IDs, strictly preventing individual history from appearing in both training and test sets.
2. **Causal Time Ordering**: Features at period $t$ predict outcomes only at period $t+1$. Future features are strictly excluded.
3. **Target Leakage Prohibition**: Survey items (`cbi_w1`..`cbi_w7`) are never used as predictors when predicting composite burnout scores computed from those items.
4. **No Commercial Use of Real Academic Librarian Data**: Real librarian data remains isolated for measurement validation and is not included in training commercial models.
5. **Decision Support Only**: Predictions serve to highlight early risk and guide supportive interventions (e.g. workload review, meeting guardrails); they must not be used for adverse employment decisions.
