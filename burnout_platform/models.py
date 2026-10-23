"""Model training, evaluation, and clustering module for the Burnout Platform.

Supports:
- Regression models: Mean Baseline, Ridge, RandomForest, HistGradientBoosting, XGBoost (if installed)
- Classification models: Majority Baseline, LogisticRegression, RandomForest, HistGradientBoosting, CalibratedClassifierCV
- Longitudinal forecasting models: Persistence Baseline, Group-aware Regressors & Classifiers
- K-Means employee segmentation
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

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
from sklearn.cluster import KMeans
from sklearn.model_selection import train_test_split, GroupKFold
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

# Safe optional XGBoost import
try:
    from xgboost import XGBRegressor, XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    XGBRegressor = None
    XGBClassifier = None

RANDOM_STATE = 42


def make_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    """Build a standard scikit-learn ColumnTransformer for numerical and categorical features."""
    numeric = X.select_dtypes(include=np.number).columns.tolist()
    categorical = X.select_dtypes(exclude=np.number).columns.tolist()

    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])

    categorical_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    return ColumnTransformer([
        ("numeric", numeric_pipe, numeric),
        ("categorical", categorical_pipe, categorical),
    ], remainder="drop")


def train_and_compare_models(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preprocessor: Optional[ColumnTransformer] = None,
) -> tuple[dict[str, dict[str, float]], dict[str, Pipeline], str]:
    """Train and evaluate continuous regression candidates (Mean Baseline, Ridge, RF, HistGB, XGBoost)."""
    if preprocessor is None:
        preprocessor = make_preprocessor(X_train)

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

    if HAS_XGBOOST and XGBRegressor is not None:
        models["xgboost"] = XGBRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.05, subsample=0.85,
            objective="reg:squarederror", n_jobs=-1, random_state=RANDOM_STATE
        )

    comparison = {}
    fitted = {}

    for name, estimator in models.items():
        pipe = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
        pipe.fit(X_train, y_train)
        pred = pipe.predict(X_test)

        mae = float(mean_absolute_error(y_test, pred))
        rmse = float(mean_squared_error(y_test, pred) ** 0.5)
        r2 = float(r2_score(y_test, pred))

        comparison[name] = {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "r2": round(r2, 4),
        }
        fitted[name] = pipe

    # Best regressor selected by lowest RMSE
    best_name = min(
        [k for k in comparison if k != "mean_baseline"],
        key=lambda n: comparison[n]["rmse"],
    )
    return comparison, fitted, best_name


def find_optimal_threshold(
    y_val: np.ndarray,
    probs_val: np.ndarray,
    min_thresh: float = 0.10,
    max_thresh: float = 0.90,
    steps: int = 81,
) -> tuple[float, float]:
    """Find the classification probability threshold on validation data that maximizes F1 score."""
    thresholds = np.linspace(min_thresh, max_thresh, steps)
    best_f1 = -1.0
    best_thresh = 0.50
    for t in thresholds:
        preds = (probs_val >= t).astype(int)
        score = f1_score(y_val, preds, zero_division=0)
        if score > best_f1:
            best_f1 = float(score)
            best_thresh = float(t)
    return round(best_thresh, 4), round(best_f1, 4)


def train_and_compare_classifiers(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preprocessor: Optional[ColumnTransformer] = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Pipeline], str, float]:
    """Train and evaluate elevated-risk binary classifiers.
    
    Tunes decision thresholds on validation data, evaluates calibration, and reports test metrics.
    """
    if preprocessor is None:
        preprocessor = make_preprocessor(X_train)

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

    comparison = {}
    fitted = {}
    val_thresholds = {}

    for name, estimator in classifiers.items():
        pipe = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
        pipe.fit(X_train, y_train)

        # Validation probabilities & threshold tuning
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
        pred_test_default = (test_probs >= 0.50).astype(int)
        pred_test_tuned = (test_probs >= best_t).astype(int)

        comparison[name] = {
            "roc_auc": round(roc_auc, 4),
            "pr_auc": round(pr_auc, 4),
            "brier_score": round(brier, 4),
            "f1_at_0_5": round(float(f1_score(y_test, pred_test_default, zero_division=0)), 4),
            "precision_at_0_5": round(float(precision_score(y_test, pred_test_default, zero_division=0)), 4),
            "recall_at_0_5": round(float(recall_score(y_test, pred_test_default, zero_division=0)), 4),
            "val_optimal_threshold": best_t,
            "f1_at_val_threshold": round(float(f1_score(y_test, pred_test_tuned, zero_division=0)), 4),
            "precision_at_val_threshold": round(float(precision_score(y_test, pred_test_tuned, zero_division=0)), 4),
            "recall_at_val_threshold": round(float(recall_score(y_test, pred_test_tuned, zero_division=0)), 4),
        }
        fitted[name] = pipe

    # Best classifier selected by PR-AUC and ROC-AUC
    valid_candidates = [k for k in comparison if k != "majority_baseline"]
    best_name = max(valid_candidates, key=lambda n: (comparison[n]["pr_auc"], comparison[n]["roc_auc"]))
    best_threshold = val_thresholds[best_name]

    return comparison, fitted, best_name, best_threshold


def fit_calibrated_risk_model(
    X_train: pd.DataFrame,
    y_train_binary: pd.Series,
    preprocessor: ColumnTransformer,
    base_model: Optional[Any] = None,
) -> Pipeline:
    """Fit a calibrated risk model using CalibratedClassifierCV to guarantee reliable probability estimates."""
    if base_model is None:
        base_model = HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE
        )

    # 5-fold cross-validation calibration
    calibrated_clf = CalibratedClassifierCV(
        estimator=base_model,
        method="sigmoid",
        cv=5,
    )
    risk_pipeline = Pipeline([("preprocessor", preprocessor), ("model", calibrated_clf)])
    risk_pipeline.fit(X_train, y_train_binary)
    return risk_pipeline


def evaluate_forecasting_pipeline(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_score_col: str = "target_next_cbi_work_score",
    target_risk_col: str = "target_next_high_burnout",
    baseline_score_col: str = "cbi_work_score",
    employee_id_col: str = "employee_id",
    test_share: float = 0.20,
) -> dict[str, Any]:
    """Evaluate next-period numerical forecasting with grouped employee split.
    
    Compares:
    - Regression: Persistence baseline (y_{t+1} = y_t), Mean baseline, Ridge, RF, HistGB
    - Classification: Persistence baseline, Majority baseline, LogisticRegression, RF, HistGB
    """
    # Group split by employee_id to strictly prevent person-level leakage across time
    unique_employees = df[employee_id_col].unique()
    rng = np.random.default_rng(RANDOM_STATE)
    test_employees = set(rng.choice(unique_employees, size=int(len(unique_employees) * test_share), replace=False))

    is_test = df[employee_id_col].isin(test_employees)
    train_df = df[~is_test].copy()
    test_df = df[is_test].copy()

    X_train = train_df[feature_cols]
    y_train_score = train_df[target_score_col]
    y_train_risk = train_df[target_risk_col].fillna(0).astype(int)

    X_test = test_df[feature_cols]
    y_test_score = test_df[target_score_col]
    y_test_risk = test_df[target_risk_col].fillna(0).astype(int)

    # 1. Regression Forecasting
    preprocessor = make_preprocessor(X_train)
    reg_models: dict[str, Any] = {
        "persistence_baseline": None,
        "mean_baseline": DummyRegressor(strategy="mean"),
        "ridge": Ridge(alpha=5.0),
        "random_forest": RandomForestRegressor(n_estimators=100, max_depth=10, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE),
        "hist_gradient_boosting": HistGradientBoostingRegressor(max_iter=120, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE),
    }

    reg_results = {}
    for name, model in reg_models.items():
        if name == "persistence_baseline":
            pred = test_df[baseline_score_col].fillna(y_train_score.mean()).to_numpy()
        else:
            pipe = Pipeline([("preprocessor", preprocessor), ("model", model)])
            pipe.fit(X_train, y_train_score)
            pred = pipe.predict(X_test)

        mae = float(mean_absolute_error(y_test_score, pred))
        rmse = float(mean_squared_error(y_test_score, pred) ** 0.5)
        r2 = float(r2_score(y_test_score, pred))
        reg_results[name] = {"mae": round(mae, 4), "rmse": round(rmse, 4), "r2": round(r2, 4)}

    # 2. Risk Classification Forecasting
    clf_models: dict[str, Any] = {
        "persistence_baseline": None,
        "majority_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        "random_forest": RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=120, learning_rate=0.07, max_leaf_nodes=31, random_state=RANDOM_STATE),
    }

    clf_results = {}
    for name, model in clf_models.items():
        if name == "persistence_baseline":
            pred = (test_df[baseline_score_col] >= 50.0).astype(int).to_numpy()
            probs = (test_df[baseline_score_col] / 100.0).clip(0, 1).to_numpy()
            roc = float(roc_auc_score(y_test_risk, probs))
            pr_auc = float(average_precision_score(y_test_risk, probs))
        else:
            pipe = Pipeline([("preprocessor", preprocessor), ("model", model)])
            pipe.fit(X_train, y_train_risk)
            probs = pipe.predict_proba(X_test)[:, 1] if hasattr(pipe, "predict_proba") else np.zeros(len(y_test_risk))
            pred = (probs >= 0.50).astype(int)
            roc = float(roc_auc_score(y_test_risk, probs)) if probs.max() > 0 else 0.5000
            pr_auc = float(average_precision_score(y_test_risk, probs)) if probs.max() > 0 else float(y_test_risk.mean())

        f1 = float(f1_score(y_test_risk, pred, zero_division=0))
        prec = float(precision_score(y_test_risk, pred, zero_division=0))
        rec = float(recall_score(y_test_risk, pred, zero_division=0))

        clf_results[name] = {
            "roc_auc": round(roc, 4),
            "pr_auc": round(pr_auc, 4),
            "f1": round(f1, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
        }

    return {
        "total_records": len(df),
        "train_records": len(train_df),
        "test_records": len(test_df),
        "unique_employees": len(unique_employees),
        "train_employees": len(unique_employees) - len(test_employees),
        "test_employees": len(test_employees),
        "regression": reg_results,
        "classification": clf_results,
    }


def perform_segmentation(df: pd.DataFrame) -> pd.DataFrame:
    """Segment employees based on Workload Index, Wellness Score, and Burnout Score."""
    df = df.copy()

    features = ["burnout_score"]
    X_cluster = df[features].fillna(df[features].median())

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_cluster)

    kmeans = KMeans(n_clusters=4, random_state=RANDOM_STATE, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)

    centroids = scaler.inverse_transform(kmeans.cluster_centers_)

    cluster_names = {}
    for i, center in enumerate(centroids):
        bo = center[0]
        if bo >= 5.0:
            cluster_names[i] = "Overloaded (At Risk)"
        elif bo <= 2.0:
            cluster_names[i] = "Healthy & Balanced"
        elif bo <= 3.5:
            cluster_names[i] = "Moderate / Transitioning"
        else:
            cluster_names[i] = "Elevated Vigilance"

    df["employee_segment"] = [cluster_names.get(c, f"Segment {c}") for c in clusters]
    return df
