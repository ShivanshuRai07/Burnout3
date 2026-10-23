"""Stage 2 - Predict: forecast next month's CBI score from this month's record.

Training pairs are consecutive months (t, t+1) of the same employee with a score at both.
Train/test split is by employee, so nobody appears on both sides. The model must beat the
persistence baseline (next month = this month) to be worth using; the 95% interval comes
from held-out residuals and its coverage is reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from burnoutiq.schema import MONTHLY_OPTIONAL

CATEGORICAL = ["department", "role_type", "work_mode"]


def next_period(period: pd.Series) -> pd.Series:
    return (pd.PeriodIndex(period, freq="M") + 1).astype(str)


def transition_pairs(records: pd.DataFrame) -> pd.DataFrame:
    """records: monthly rows with cbi_work_score -> rows of features at t plus target_next at t+1."""
    scored = records[records["cbi_work_score"].notna()]
    nxt = scored[["employee_id", "period", "cbi_work_score"]].rename(
        columns={"period": "next_period", "cbi_work_score": "target_next"})
    cur = scored.assign(next_period=next_period(scored["period"]))
    return cur.merge(nxt, on=["employee_id", "next_period"], how="inner")


def _rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


@dataclass
class ForecastModel:
    numeric: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    pipeline: Pipeline | None = None
    residual_sd: float = float("nan")
    metrics: dict = field(default_factory=dict)
    test_employees: set = field(default_factory=set)

    @property
    def interval_95(self) -> float:
        return 1.96 * self.residual_sd

    def fit(self, records: pd.DataFrame, test_size: float = 0.2, seed: int = 42) -> "ForecastModel":
        pairs = transition_pairs(records)
        if len(pairs) < 50:
            raise ValueError(f"only {len(pairs)} consecutive-month pairs; need at least 50 to train a forecast")
        self.numeric = ["cbi_work_score"] + [c for c in MONTHLY_OPTIONAL
                                            if c in pairs.columns and pairs[c].notna().mean() > 0.5]
        self.categorical = [c for c in CATEGORICAL if c in pairs.columns]
        split = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        tr, te = next(split.split(pairs, groups=pairs["employee_id"]))
        train, test = pairs.iloc[tr], pairs.iloc[te]
        self.test_employees = set(test["employee_id"])

        pre = ColumnTransformer([
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), self.numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore"), self.categorical),
        ])
        self.pipeline = Pipeline([("pre", pre), ("model", Ridge(alpha=1.0))])
        self.pipeline.fit(train[self.features], train["target_next"])

        pred = self.predict_mean(test)
        resid = test["target_next"] - pred
        self.residual_sd = float(resid.std(ddof=1))
        persistence = test["cbi_work_score"]
        self.metrics = {
            "train_pairs": int(len(train)), "test_pairs": int(len(test)),
            "train_employees": int(train["employee_id"].nunique()), "test_employees": int(test["employee_id"].nunique()),
            "model": {"mae": round(mean_absolute_error(test["target_next"], pred), 3),
                      "rmse": round(_rmse(test["target_next"], pred), 3),
                      "r2": round(r2_score(test["target_next"], pred), 3)},
            "persistence": {"mae": round(mean_absolute_error(test["target_next"], persistence), 3),
                            "rmse": round(_rmse(test["target_next"], persistence), 3),
                            "r2": round(r2_score(test["target_next"], persistence), 3)},
            "interval_95_halfwidth": round(self.interval_95, 2),
            "interval_95_coverage": round(float((resid.abs() <= self.interval_95).mean()), 3),
        }
        self.metrics["beats_persistence"] = self.metrics["model"]["mae"] < self.metrics["persistence"]["mae"]
        return self

    @property
    def features(self) -> list[str]:
        return self.numeric + self.categorical

    def predict_mean(self, records: pd.DataFrame) -> np.ndarray:
        x = records.reindex(columns=self.features)
        return np.clip(self.pipeline.predict(x), 0, 100)

    def predict(self, records: pd.DataFrame) -> pd.DataFrame:
        mean = self.predict_mean(records)
        return pd.DataFrame({"forecast": mean.round(2),
                             "forecast_low": np.clip(mean - self.interval_95, 0, 100).round(2),
                             "forecast_high": np.clip(mean + self.interval_95, 0, 100).round(2)},
                            index=records.index)
