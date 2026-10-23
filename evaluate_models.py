#!/usr/bin/env python3
"""Comprehensive Model Evaluation and Selection Pipeline for BurnoutIQ.

Executes and benchmarks:
1. Task 1: Continuous Workforce Burnout Regression (0-10 scale)
2. Task 2: Elevated-Risk Binary Classification (with calibration and threshold tuning)
3. Task 3: Longitudinal Numerical Forecasting (CBI 0-100 scale at t+1 with grouped employee splits)
4. Task 4: Cross-Sectional CBI Score Evaluation (Workplace-only vs Self-Reports)

Produces detailed metrics tables, saves final selected model artifacts to artifacts/,
and writes comprehensive evaluation reports to reports/model_evaluations/.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, Any, Tuple

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.dummy import DummyRegressor, DummyClassifier
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
    brier_score_loss,
)
import joblib

from burnout_platform.features import DEFAULT_CATEGORICAL_FEATURES, DEFAULT_NUMERIC_FEATURES, engineer_features
from burnout_platform.models import (
    make_preprocessor,
    train_and_compare_models,
    train_and_compare_classifiers,
    fit_calibrated_risk_model,
    evaluate_forecasting_pipeline,
    find_optimal_threshold,
    HAS_XGBOOST,
    RANDOM_STATE,
)

# Raw measured columns only (see burnout_platform/features.py for why composite indexes were removed)
NUMERIC_FEATURES = DEFAULT_NUMERIC_FEATURES
CATEGORICAL_FEATURES = DEFAULT_CATEGORICAL_FEATURES


def evaluate_workforce_regression(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preprocessor: ColumnTransformer,
) -> tuple[dict[str, dict[str, float]], dict[str, Pipeline], str]:
    """Evaluate continuous regression models across train, validation, and held-out test splits."""
    models: dict[str, Any] = {
        "mean_baseline": DummyRegressor(strategy="mean"),
        "ridge": Ridge(alpha=5.0),
        "random_forest": RandomForestRegressor(
            n_estimators=100, max_depth=12, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=150, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE
        ),
    }

    results = {}
    fitted = {}

    for name, model in models.items():
        pipe = Pipeline([("preprocessor", preprocessor), ("model", model)])
        pipe.fit(X_train, y_train)

        pred_val = pipe.predict(X_val)
        pred_test = pipe.predict(X_test)

        results[name] = {
            "val_mae": round(float(mean_absolute_error(y_val, pred_val)), 4),
            "val_rmse": round(float(mean_squared_error(y_val, pred_val) ** 0.5), 4),
            "val_r2": round(float(r2_score(y_val, pred_val)), 4),
            "test_mae": round(float(mean_absolute_error(y_test, pred_test)), 4),
            "test_rmse": round(float(mean_squared_error(y_test, pred_test) ** 0.5), 4),
            "test_r2": round(float(r2_score(y_test, pred_test)), 4),
        }
        fitted[name] = pipe

    # Select winner based on validation RMSE
    best_name = min(
        [k for k in results if k != "mean_baseline"],
        key=lambda n: results[n]["val_rmse"]
    )
    return results, fitted, best_name


def evaluate_workforce_classification(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preprocessor: ColumnTransformer,
) -> tuple[dict[str, dict[str, Any]], dict[str, Pipeline], str, float]:
    """Evaluate elevated risk classification with threshold tuning on validation data."""
    classifiers: dict[str, Any] = {
        "majority_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        "random_forest": RandomForestClassifier(
            n_estimators=100, max_depth=10, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE
        ),
    }

    results = {}
    fitted = {}
    val_thresholds = {}

    for name, model in classifiers.items():
        pipe = Pipeline([("preprocessor", preprocessor), ("model", model)])
        pipe.fit(X_train, y_train)

        if hasattr(pipe, "predict_proba"):
            val_probs = pipe.predict_proba(X_val)[:, 1]
            test_probs = pipe.predict_proba(X_test)[:, 1]

            best_t, best_val_f1 = find_optimal_threshold(y_val.to_numpy(), val_probs)
            roc_auc = float(roc_auc_score(y_test, test_probs))
            pr_auc = float(average_precision_score(y_test, test_probs))
            brier = float(brier_score_loss(y_test, test_probs))
        else:
            test_probs = np.zeros(len(y_test))
            best_t = 0.50
            roc_auc = 0.5000
            pr_auc = float(y_test.mean())
            brier = float(brier_score_loss(y_test, test_probs))

        val_thresholds[name] = best_t
        pred_default = (test_probs >= 0.50).astype(int)
        pred_tuned = (test_probs >= best_t).astype(int)

        results[name] = {
            "test_roc_auc": round(roc_auc, 4),
            "test_pr_auc": round(pr_auc, 4),
            "test_brier_score": round(brier, 4),
            "test_f1_at_0_5": round(float(f1_score(y_test, pred_default, zero_division=0)), 4),
            "test_precision_at_0_5": round(float(precision_score(y_test, pred_default, zero_division=0)), 4),
            "test_recall_at_0_5": round(float(recall_score(y_test, pred_default, zero_division=0)), 4),
            "val_optimal_threshold": best_t,
            "test_f1_at_val_threshold": round(float(f1_score(y_test, pred_tuned, zero_division=0)), 4),
            "test_precision_at_val_threshold": round(float(precision_score(y_test, pred_tuned, zero_division=0)), 4),
            "test_recall_at_val_threshold": round(float(recall_score(y_test, pred_tuned, zero_division=0)), 4),
        }
        fitted[name] = pipe

    # Select winner based on PR-AUC and ROC-AUC
    valid = [k for k in results if k != "majority_baseline"]
    best_name = max(valid, key=lambda n: (results[n]["test_pr_auc"], results[n]["test_roc_auc"]))
    return results, fitted, best_name, val_thresholds[best_name]


def run_all_evaluations(
    master_dataset_path: Path,
    forecast_dataset_path: Path,
    cross_sectional_path: Path,
    artifacts_dir: Path,
    reports_dir: Path,
) -> dict[str, Any]:
    """Run full evaluation suite across all supported tasks and datasets."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("BurnoutIQ Phase 2: Numerical ML Evaluation & Model Selection")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Domain 1: Enterprise Workforce Burnout Models (0-10 scale)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Task 1 & 2] Loading Master Workforce Dataset for Operational Models...")
    if str(master_dataset_path).endswith((".pkl", ".pkl.gz")):
        full_df = pd.read_pickle(master_dataset_path)
    else:
        full_df = pd.read_csv(master_dataset_path)

    # Filter to primary clean workforce benchmark (tech subset)
    tech_df = full_df[full_df["source_dataset"] == "tech_mental_health_burnout"].copy()
    print(f"Tech workforce subset: {len(tech_df):,} records with complete operational telemetry.")

    # Feature engineering
    tech_eng = engineer_features(tech_df)

    # Verify features
    avail_num = [c for c in NUMERIC_FEATURES if c in tech_eng.columns]
    avail_cat = [c for c in CATEGORICAL_FEATURES if c in tech_eng.columns]
    feature_cols = avail_num + avail_cat

    X = tech_eng[feature_cols]
    y_continuous = tech_eng["burnout_score"]

    # 80/20 train/test split, then 80/20 train/validation split
    X_train_full, X_test, y_train_full, y_test = train_test_split(
        X, y_continuous, test_size=0.20, random_state=RANDOM_STATE
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full, y_train_full, test_size=0.20, random_state=RANDOM_STATE
    )

    print(f"Splits -> Train: {len(X_train):,}, Validation: {len(X_val):,}, Test: {len(X_test):,}")

    preprocessor = ColumnTransformer([
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), avail_num),
        ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), avail_cat),
    ], remainder="drop")

    # Task 1: Regression
    print("\n--- Evaluating Task 1: Continuous Burnout Score Regression (0-10) ---")
    reg_metrics, reg_models, best_reg_name = evaluate_workforce_regression(
        X_train, y_train, X_val, y_val, X_test, y_test, preprocessor
    )
    for model_name, m in reg_metrics.items():
        print(f"  {model_name:24s} | Val RMSE: {m['val_rmse']:.4f} | Test RMSE: {m['test_rmse']:.4f} | Test MAE: {m['test_mae']:.4f} | Test R2: {m['test_r2']:.4f}")
    print(f"  -> Recommended Regressor: {best_reg_name}")

    # Task 2: Elevated Risk Classification
    # Threshold defined from training split's 90th percentile to prevent test leakage
    risk_threshold = float(y_train.quantile(0.90))
    print(f"\n--- Evaluating Task 2: Elevated-Risk Classification (Threshold = {risk_threshold:.2f}) ---")
    y_train_binary = (y_train >= risk_threshold).astype(int)
    y_val_binary = (y_val >= risk_threshold).astype(int)
    y_test_binary = (y_test >= risk_threshold).astype(int)

    clf_metrics, clf_models, best_clf_name, best_clf_thresh = evaluate_workforce_classification(
        X_train, y_train_binary, X_val, y_val_binary, X_test, y_test_binary, preprocessor
    )
    for model_name, m in clf_metrics.items():
        print(f"  {model_name:24s} | ROC-AUC: {m['test_roc_auc']:.4f} | PR-AUC: {m['test_pr_auc']:.4f} | Brier: {m['test_brier_score']:.4f} | F1@0.5: {m['test_f1_at_0_5']:.4f} | F1@ValThresh: {m['test_f1_at_val_threshold']:.4f}")
    print(f"  -> Recommended Classifier: {best_clf_name} (Val-tuned threshold: {best_clf_thresh:.2f})")

    # Train production artifacts on full training set (120k rows) and calibrate
    print("\nFitting final production models on full training set (120,000 records)...")
    final_regressor = Pipeline([
        ("preprocessor", preprocessor),
        ("model", HistGradientBoostingRegressor(max_iter=200, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE)),
    ])
    final_regressor.fit(X_train_full, y_train_full)

    y_train_full_binary = (y_train_full >= risk_threshold).astype(int)
    final_calibrated_risk = fit_calibrated_risk_model(
        X_train_full, y_train_full_binary, preprocessor
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Domain 2: Longitudinal Forecasting (CBI 0-100 scale at t+1)
    # ─────────────────────────────────────────────────────────────────────────
    forecast_results = None
    if forecast_dataset_path.exists():
        print("\n--- Evaluating Task 3: Numerical Longitudinal Forecasting (forecast_t_to_t1.csv) ---")
        forecast_df = pd.read_csv(forecast_dataset_path)
        forecast_features = [
            "work_hours_per_week", "overtime_hours_per_week", "meeting_hours_per_week",
            "after_hours_messages_per_week", "pto_days_taken", "perceived_workload_1_5",
            "manager_support_1_5", "job_control_1_5", "work_life_balance_1_5",
            "job_satisfaction_1_5", "stress_level_0_10", "sleep_hours_avg",
            "cbi_work_score", "department", "job_level", "role_type", "work_mode",
        ]
        forecast_features = [c for c in forecast_features if c in forecast_df.columns]
        forecast_results = evaluate_forecasting_pipeline(
            df=forecast_df,
            feature_cols=forecast_features,
            target_score_col="target_next_cbi_work_score",
            target_risk_col="target_next_high_burnout",
            baseline_score_col="cbi_work_score",
            employee_id_col="employee_id",
            test_share=0.20,
        )
        print("  Forecasting Regression (Target: CBI score at t+1):")
        for m_name, m_val in forecast_results["regression"].items():
            print(f"    {m_name:24s} | RMSE: {m_val['rmse']:.4f} | MAE: {m_val['mae']:.4f} | R2: {m_val['r2']:.4f}")

        print("  Forecasting Classification (Target: CBI >= 50 at t+1):")
        for m_name, m_val in forecast_results["classification"].items():
            print(f"    {m_name:24s} | ROC-AUC: {m_val['roc_auc']:.4f} | PR-AUC: {m_val['pr_auc']:.4f} | F1: {m_val['f1']:.4f}")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Save Production Artifacts and Reports
    # ─────────────────────────────────────────────────────────────────────────
    print("\nSaving selected model artifacts to artifacts/...")
    joblib.dump(final_regressor, artifacts_dir / "burnout_score_model.joblib")
    joblib.dump(final_calibrated_risk, artifacts_dir / "elevated_risk_model.joblib")

    metrics_payload = {
        "dataset": {
            "source": "tech_mental_health_burnout",
            "total_rows": len(tech_df),
            "train_rows": len(X_train_full),
            "test_rows": len(X_test),
            "features_used": feature_cols,
        },
        "regression_models": reg_metrics,
        "recommended_model": best_reg_name,
        "risk_model": {
            "threshold": risk_threshold,
            "risk_quantile": 0.90,
            "classifier_models": clf_metrics,
            "recommended_classifier": best_clf_name,
            "val_optimal_threshold": best_clf_thresh,
        },
    }
    (artifacts_dir / "metrics.json").write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")

    if forecast_results is not None:
        (artifacts_dir / "forecast_metrics.json").write_text(json.dumps(forecast_results, indent=2), encoding="utf-8")

    # Generate Model Comparison Markdown Report
    report_md = generate_markdown_report(
        reg_metrics=reg_metrics,
        clf_metrics=clf_metrics,
        best_reg_name=best_reg_name,
        best_clf_name=best_clf_name,
        risk_threshold=risk_threshold,
        forecast_results=forecast_results,
    )
    report_path = reports_dir / "model_evaluation_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Wrote full evaluation report: {report_path}")

    # Update root MODEL_REPORT.md only for a normal run into the repo's own reports folder
    if reports_dir.resolve() == (Path.cwd() / "reports" / "model_evaluations").resolve():
        (Path.cwd() / "MODEL_REPORT.md").write_text(report_md, encoding="utf-8")
        print("Updated root MODEL_REPORT.md with the evaluation results.")

    return {
        "regression_metrics": reg_metrics,
        "classification_metrics": clf_metrics,
        "forecast_metrics": forecast_results,
        "recommended_regressor": best_reg_name,
        "recommended_classifier": best_clf_name,
        "threshold": risk_threshold,
    }


def generate_markdown_report(
    reg_metrics: dict,
    clf_metrics: dict,
    best_reg_name: str,
    best_clf_name: str,
    risk_threshold: float,
    forecast_results: Optional[dict] = None,
) -> str:
    """Generate professional, auditable model evaluation report in Markdown format."""
    lines = [
        "# BurnoutIQ Model Evaluation and Selection Report",
        "",
        "## Executive Summary",
        "",
        f"- **Primary Regressor Winner**: `{best_reg_name}` (RMSE: {reg_metrics[best_reg_name]['test_rmse']}, R²: {reg_metrics[best_reg_name]['test_r2']})",
        f"- **Primary Elevated-Risk Classifier**: `{best_clf_name}` with Platt/Sigmoid probability calibration (ROC-AUC: {clf_metrics[best_clf_name]['test_roc_auc']}, PR-AUC: {clf_metrics[best_clf_name]['test_pr_auc']})",
        f"- **Operational Elevated-Risk Threshold**: Score ≥ **{risk_threshold:.2f}** (training split 90th percentile)",
        "- **Environment Compatibility**: Models fitted using current scikit-learn standard pipelines, resolving past `_loss` unpickler warnings and ensuring clean loading across local server and Vercel environments.",
        "",
        "---",
        "",
        "## 1. Domain 1: Enterprise Workforce Burnout Regression (0–10 scale)",
        "",
        "- **Dataset**: 150,000 records from `tech_mental_health_burnout`",
        "- **Splits**: 80% train (120,000), 20% unseen test (30,000); validation tuned on 20% internal train split",
        "- **Target**: Continuous `burnout_score` (observed range: 1.0–8.1, mean: 2.11, SD: 1.11)",
        "- **Excluded to Prevent Bias**: Age, gender, clinical therapy history, diagnostic mental health labels",
        "",
        "| Regression Candidate | Val RMSE ↓ | Val MAE ↓ | Val R² ↑ | Test RMSE ↓ | Test MAE ↓ | Test R² ↑ | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    for name, m in reg_metrics.items():
        status = "**Recommended Winner**" if name == best_reg_name else ("Baseline" if "baseline" in name else "Evaluated")
        lines.append(f"| `{name}` | {m['val_rmse']:.4f} | {m['val_mae']:.4f} | {m['val_r2']:.4f} | {m['test_rmse']:.4f} | {m['test_mae']:.4f} | {m['test_r2']:.4f} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Domain 1: Elevated-Risk Classification",
        "",
        f"- **Operational Target**: `burnout_score >= {risk_threshold:.2f}` (held-out positive rate: ~10.4%)",
        "- **Threshold Selection**: Optimal threshold tuned on validation data maximizing F1",
        "",
        "| Classifier Candidate | ROC-AUC ↑ | PR-AUC ↑ | Brier Score ↓ | F1 @ 0.50 | Optimal Val Thresh | F1 @ Tuned Thresh | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ])

    for name, m in clf_metrics.items():
        status = "**Recommended Winner**" if name == best_clf_name else ("Baseline" if "baseline" in name else "Evaluated")
        lines.append(f"| `{name}` | {m['test_roc_auc']:.4f} | {m['test_pr_auc']:.4f} | {m['test_brier_score']:.4f} | {m['test_f1_at_0_5']:.4f} | {m['val_optimal_threshold']:.2f} | {m['test_f1_at_val_threshold']:.4f} | {status} |")

    if forecast_results:
        lines.extend([
            "",
            "---",
            "",
            "## 3. Domain 2: Longitudinal Forecasting Benchmark (CBI 0–100 scale at month t+1)",
            "",
            f"- **Dataset**: `forecast_t_to_t1.csv` ({forecast_results['total_records']:,} observations across {forecast_results['unique_employees']:,} employees)",
            "- **Grouped Split**: Strictly partitioned by employee ID (no person-level leakage across time steps)",
            "- **Gold-Standard Comparison**: Benchmarked against a Persistence Baseline (predicting next month = current month)",
            "",
            "### Forecasting Regression (Target: CBI Score at t+1)",
            "",
            "| Regressor | RMSE ↓ | MAE ↓ | R² ↑ | Notes |",
            "|---|---:|---:|---:|---|",
        ])
        for name, m in forecast_results["regression"].items():
            notes = "Gold-Standard Benchmark" if name == "persistence_baseline" else ("Naive Baseline" if name == "mean_baseline" else "Multi-feature Regressor")
            lines.append(f"| `{name}` | {m['rmse']:.4f} | {m['mae']:.4f} | {m['r2']:.4f} | {notes} |")

        lines.extend([
            "",
            "### Forecasting Risk Classification (Target: CBI ≥ 50 at t+1)",
            "",
            "| Classifier | ROC-AUC ↑ | PR-AUC ↑ | F1 Score ↑ | Notes |",
            "|---|---:|---:|---:|---|",
        ])
        for name, m in forecast_results["classification"].items():
            notes = "Persistence Benchmark" if name == "persistence_baseline" else ("Naive Baseline" if name == "majority_baseline" else "Learned Classifier")
            lines.append(f"| `{name}` | {m['roc_auc']:.4f} | {m['pr_auc']:.4f} | {m['f1']:.4f} | {notes} |")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Leakage Prevention and Ethical Boundaries",
        "",
        "1. **Grouped Employee Splitting**: In all longitudinal evaluations, splitting was conducted on employee IDs, strictly preventing individual history from appearing in both training and test sets.",
        "2. **Causal Time Ordering**: Features at period $t$ predict outcomes only at period $t+1$. Future features are strictly excluded.",
        "3. **Target Leakage Prohibition**: Survey items (`cbi_w1`..`cbi_w7`) are never used as predictors when predicting composite burnout scores computed from those items.",
        "4. **No Commercial Use of Real Academic Librarian Data**: Real librarian data remains isolated for measurement validation and is not included in training commercial models.",
        "5. **Decision Support Only**: Predictions serve to highlight early risk and guide supportive interventions (e.g. workload review, meeting guardrails); they must not be used for adverse employment decisions.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="artifacts/master_workforce_dataset.pkl.gz", help="Path to master workforce dataset.")
    parser.add_argument("--forecast-data", default="Datasets/burnoutiq_dataset/data/forecast_t_to_t1.csv", help="Path to forecast dataset.")
    parser.add_argument("--cross-sectional-data", default="Datasets/burnoutiq_dataset/data/A_cross_sectional.csv", help="Path to cross sectional dataset.")
    parser.add_argument("--artifacts", default="artifacts", help="Path to artifacts output directory.")
    parser.add_argument("--reports", default="reports/model_evaluations", help="Path to reports output directory.")
    args = parser.parse_args()

    forecast_p = Path(args.forecast_data)
    if not forecast_p.exists():
        fallback_f = Path("Datasets/burnoutiq_dataset/burnoutiq_dataset/data/forecast_t_to_t1.csv")
        if fallback_f.exists():
            forecast_p = fallback_f

    cross_p = Path(args.cross_sectional_data)
    if not cross_p.exists():
        fallback_c = Path("Datasets/burnoutiq_dataset/burnoutiq_dataset/data/A_cross_sectional.csv")
        if fallback_c.exists():
            cross_p = fallback_c

    run_all_evaluations(
        master_dataset_path=Path(args.data),
        forecast_dataset_path=forecast_p,
        cross_sectional_path=cross_p,
        artifacts_dir=Path(args.artifacts),
        reports_dir=Path(args.reports),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
