"""Retrain the 0-10 snapshot models from data in this repo, then run the self-report ablation.

  python train.py                         # retrain into artifacts/ and write reports
  python train.py --artifacts out/ --skip-models   # ablation only

The snapshot models are trained by evaluate_models.py on the tech workforce subset of
artifacts/master_workforce_dataset.pkl.gz. The ablation answers: how much of the accuracy comes from
self-reported stress and wellbeing, which are measured at the same time as the burnout score?
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from burnout_platform.features import engineer_features
from evaluate_models import CATEGORICAL_FEATURES, NUMERIC_FEATURES, RANDOM_STATE, run_all_evaluations

MASTER = Path("artifacts/master_workforce_dataset.pkl.gz")
SOURCE = "tech_mental_health_burnout"
SELF_REPORTED_WELLBEING = ["stress_level", "work_life_balance", "job_satisfaction", "sleep_hours",
                           "social_support_score", "physical_activity_days", "caffeine_intake",
                           "screen_time_hours"]
FEATURE_SETS = {
    "all features": NUMERIC_FEATURES,
    "without stress_level": [c for c in NUMERIC_FEATURES if c != "stress_level"],
    "workplace only (no self-reported wellbeing)": [c for c in NUMERIC_FEATURES if c not in SELF_REPORTED_WELLBEING],
}


def self_report_ablation(out_dir: Path) -> pd.DataFrame:
    df = pd.read_pickle(MASTER)
    df = engineer_features(df[df["source_dataset"] == SOURCE])
    y = df["burnout_score"]
    train_idx, test_idx = train_test_split(df.index, test_size=0.2, random_state=RANDOM_STATE)
    threshold = y.loc[train_idx].quantile(0.90)
    rows = []
    for name, numeric in FEATURE_SETS.items():
        cols = numeric + CATEGORICAL_FEATURES
        pre = ColumnTransformer([
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ])
        reg = Pipeline([("pre", pre), ("m", HistGradientBoostingRegressor(random_state=RANDOM_STATE))])
        reg.fit(df.loc[train_idx, cols], y.loc[train_idx])
        pred = reg.predict(df.loc[test_idx, cols])
        clf = Pipeline([("pre", pre), ("m", HistGradientBoostingClassifier(random_state=RANDOM_STATE))])
        clf.fit(df.loc[train_idx, cols], y.loc[train_idx] >= threshold)
        prob = clf.predict_proba(df.loc[test_idx, cols])[:, 1]
        rows.append({"feature_set": name, "n_numeric_features": len(numeric),
                     "test_r2": round(r2_score(y.loc[test_idx], pred), 4),
                     "test_mae": round(mean_absolute_error(y.loc[test_idx], pred), 4),
                     "test_roc_auc_elevated": round(roc_auc_score(y.loc[test_idx] >= threshold, prob), 4)})
        print(rows[-1])
    table = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "self_report_ablation.csv", index=False)
    md = ["| " + " | ".join(table.columns) + " |", "|" + " --- |" * len(table.columns)]
    md += ["| " + " | ".join(str(v) for v in r) + " |" for r in table.itertuples(index=False)]
    (out_dir / "self_report_ablation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return table


def export_feature_importance(artifacts: Path, n_sample: int = 5000) -> pd.DataFrame:
    """Permutation importance of the live score model on held-out rows: mean drop in test R²."""
    import joblib
    from sklearn.inspection import permutation_importance

    df = pd.read_pickle(MASTER)
    df = engineer_features(df[df["source_dataset"] == SOURCE])
    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    _, x_test, _, y_test = train_test_split(df[cols], df["burnout_score"], test_size=0.2, random_state=RANDOM_STATE)
    x_test, y_test = x_test.iloc[:n_sample], y_test.iloc[:n_sample]
    model = joblib.load(artifacts / "burnout_score_model.joblib")
    res = permutation_importance(model, x_test, y_test, scoring="r2", n_repeats=5, random_state=RANDOM_STATE)
    table = (pd.DataFrame({"feature": cols, "importance": res.importances_mean.round(4),
                           "importance_sd": res.importances_std.round(4)})
             .sort_values("importance", ascending=False))
    table.to_csv(artifacts / "feature_importance.csv", index=False)
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default="artifacts")
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--skip-models", action="store_true", help="only run the ablation")
    a = ap.parse_args()
    if not a.skip_models:
        run_all_evaluations(
            master_dataset_path=MASTER,
            forecast_dataset_path=Path("Datasets/burnoutiq_dataset/data/forecast_t_to_t1.csv"),
            cross_sectional_path=Path("Datasets/burnoutiq_dataset/data/A_cross_sectional.csv"),
            artifacts_dir=Path(a.artifacts),
            reports_dir=Path(a.reports) / "model_evaluations",
        )
        print(export_feature_importance(Path(a.artifacts)).head(8).to_string(index=False))
    self_report_ablation(Path(a.reports) / "research" / "tables")


if __name__ == "__main__":
    main()
