"""Unit and integration tests for the numerical ML evaluation and model selection pipeline.

Verifies:
- Preprocessor imputation, scaling, and categorical encoding
- Regression candidate comparisons and baseline benchmarking
- Classification candidate comparisons, threshold tuning, and calibration
- Longitudinal forecasting pipeline with grouped employee splitting
- Artifact integrity and seamless inference
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import joblib

from burnout_platform.models import (
    make_preprocessor,
    train_and_compare_models,
    train_and_compare_classifiers,
    fit_calibrated_risk_model,
    evaluate_forecasting_pipeline,
    find_optimal_threshold,
)
from burnout_platform.features import engineer_features


@pytest.fixture(scope="module")
def tech_workforce_data() -> pd.DataFrame:
    df = pd.read_pickle("artifacts/master_workforce_dataset.pkl.gz")
    tech = df[df["source_dataset"] == "tech_mental_health_burnout"].copy()
    assert len(tech) == 150000
    # Sample 5,000 rows for rapid test execution
    return tech.sample(5000, random_state=42).reset_index(drop=True)


@pytest.fixture(scope="module")
def forecast_data() -> pd.DataFrame:
    path = Path("Datasets/burnoutiq_dataset/data/forecast_t_to_t1.csv")
    if not path.exists():
        path = Path("Datasets/burnoutiq_dataset/burnoutiq_dataset/data/forecast_t_to_t1.csv")
    assert path.exists(), f"Forecast dataset not found at {path}"
    return pd.read_csv(path)


def test_preprocessor_pipeline(tech_workforce_data: pd.DataFrame):
    """Verify preprocessor handles missing values, scaling, and encoding."""
    eng_df = engineer_features(tech_workforce_data)
    cols = ["work_hours_per_week", "job_role", "work_mode", "job_satisfaction"]
    X = eng_df[cols].copy()

    # Introduce synthetic missing values to test imputation
    X.loc[0, "work_hours_per_week"] = np.nan
    X.loc[1, "job_role"] = np.nan

    preproc = make_preprocessor(X)
    X_trans = preproc.fit_transform(X)

    assert not np.isnan(X_trans).any(), "Preprocessor output must not contain NaNs."
    assert X_trans.shape[0] == len(X)
    assert X_trans.shape[1] > len(cols)  # Due to one-hot encoding


def test_regression_comparison_and_baselines(tech_workforce_data: pd.DataFrame):
    """Verify regression comparison includes mean baseline and valid metrics."""
    eng_df = engineer_features(tech_workforce_data)
    cols = ["work_hours_per_week", "overtime_hours", "job_role", "work_mode", "stress_level"]
    X = eng_df[cols]
    y = eng_df["burnout_score"]

    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

    comp, fitted, best_name = train_and_compare_models(X_train, y_train, X_test, y_test)

    assert "mean_baseline" in comp
    assert "ridge" in comp
    assert "hist_gradient_boosting" in comp
    assert best_name in fitted

    # HistGradientBoosting should significantly beat the naive mean baseline
    assert comp[best_name]["rmse"] < comp["mean_baseline"]["rmse"]
    assert comp[best_name]["r2"] > 0.60


def test_classification_and_threshold_tuning(tech_workforce_data: pd.DataFrame):
    """Verify classification comparison, calibration metrics, and validation threshold tuning."""
    eng_df = engineer_features(tech_workforce_data)
    cols = ["work_hours_per_week", "overtime_hours", "job_role", "work_mode", "stress_level"]
    X = eng_df[cols]
    y_score = eng_df["burnout_score"]

    from sklearn.model_selection import train_test_split
    X_train, X_temp, y_s_train, y_s_temp = train_test_split(X, y_score, test_size=0.40, random_state=42)
    X_val, X_test, y_s_val, y_s_test = train_test_split(X_temp, y_s_temp, test_size=0.50, random_state=42)

    thresh = float(y_s_train.quantile(0.90))
    y_train = (y_s_train >= thresh).astype(int)
    y_val = (y_s_val >= thresh).astype(int)
    y_test = (y_s_test >= thresh).astype(int)

    comp, fitted, best_name, best_t = train_and_compare_classifiers(
        X_train, y_train, X_val, y_val, X_test, y_test
    )

    assert "majority_baseline" in comp
    assert "logistic_regression" in comp
    assert "hist_gradient_boosting" in comp
    assert 0.05 <= best_t <= 0.95
    assert comp[best_name]["roc_auc"] > 0.90
    assert comp[best_name]["pr_auc"] > 0.65


def test_calibrated_risk_model(tech_workforce_data: pd.DataFrame):
    """Verify CalibratedClassifierCV outputs probabilities strictly in [0, 1]."""
    eng_df = engineer_features(tech_workforce_data)
    cols = ["work_hours_per_week", "job_role", "work_mode", "stress_level"]
    X = eng_df[cols]
    y = (eng_df["burnout_score"] >= eng_df["burnout_score"].quantile(0.90)).astype(int)

    preproc = make_preprocessor(X)
    pipe = fit_calibrated_risk_model(X, y, preproc)

    probs = pipe.predict_proba(X)[:, 1]
    assert (probs >= 0.0).all() and (probs <= 1.0).all()
    # Mean probability should roughly track class base rate
    assert abs(probs.mean() - y.mean()) < 0.05


def test_forecasting_pipeline_no_person_leakage(forecast_data: pd.DataFrame):
    """Verify longitudinal forecasting performs employee-level group split and evaluates persistence."""
    features = [
        "work_hours_per_week", "overtime_hours_per_week", "meeting_hours_per_week",
        "perceived_workload_1_5", "manager_support_1_5", "cbi_work_score",
    ]
    # Sample subset of employees for rapid test
    sample_emps = forecast_data["employee_id"].unique()[:400]
    sub_df = forecast_data[forecast_data["employee_id"].isin(sample_emps)].copy()

    res = evaluate_forecasting_pipeline(
        df=sub_df,
        feature_cols=features,
        target_score_col="target_next_cbi_work_score",
        target_risk_col="target_next_high_burnout",
        baseline_score_col="cbi_work_score",
        employee_id_col="employee_id",
        test_share=0.25,
    )

    assert "persistence_baseline" in res["regression"]
    assert "ridge" in res["regression"]
    assert "hist_gradient_boosting" in res["regression"]

    # Verify no employee overlap between train and test splits
    assert res["test_employees"] > 0
    assert res["train_employees"] > 0
    assert res["test_employees"] + res["train_employees"] == len(sample_emps)


def test_production_artifacts_load_and_predict():
    """Verify saved production artifacts in artifacts/ load natively and predict correctly."""
    artifacts = Path("artifacts")
    score_model = joblib.load(artifacts / "burnout_score_model.joblib")
    risk_model = joblib.load(artifacts / "elevated_risk_model.joblib")
    metrics = json.loads((artifacts / "metrics.json").read_text(encoding="utf-8"))

    sample_input = pd.DataFrame([{
        "work_hours_per_week": 45.0,
        "overtime_hours": 6.0,
        "meetings_per_day": 4.0,
        "deadlines_missed": 1.0,
        "experience_years": 5.0,
        "job_role": "Backend Developer",
        "work_mode": "Hybrid",
        "job_satisfaction": 60.0,
        "manager_support": 50.0,
        "work_life_balance": 50.0,
        "sleep_hours": 6.5,
        "physical_activity_days": 2.0,
        "stress_level": 6.0,
        "caffeine_intake": 2.0,
        "company_size": "Large",
        "screen_time_hours": 8.0,
        "social_support_score": 5.0,
    }])
    eng_input = engineer_features(sample_input)

    pred_score = float(score_model.predict(eng_input)[0])
    pred_risk = float(risk_model.predict_proba(eng_input)[0, 1])

    assert 0.0 <= pred_score <= 10.0
    assert 0.0 <= pred_risk <= 1.0
    assert metrics["risk_model"]["threshold"] > 0.0
