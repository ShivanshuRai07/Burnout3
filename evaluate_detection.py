"""Compare burnout detection rules on employees the forecast model never saw.

Question: who will still be burned out in the coming months? Each rule flags people in month t using only
data up to t; the outcome is read from their next surveys (t+1 .. t+4).

  sustained ahead  - the next two answered surveys are both >= 50 (primary: burnout is chronic)
  high next        - the next answered survey (within 3 months) is >= 50

Rules compared
  current       - the loop's rule today: score >= 50, far above division, +10 vs own baseline, or forecast high/rising
  one month     - score >= 50 this month (the simplest rule)
  trajectory    - sustained high or reliable rise (burnoutiq.trajectory), without the missed-survey signal
  trajectory+   - trajectory plus "missed survey after a high score"

A logistic regression on the same features checks whether trajectory and missed-survey information add
signal beyond this month's score (average precision on held-out employees).

Caveat: the synthetic generator makes people with higher latent burnout less likely to answer, following the
survey-research assumption; a real pilot must confirm the missed-survey signal before it is trusted.

Usage: python evaluate_detection.py   ->  reports/DETECTION_REPORT.md and reports/detection_metrics.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from burnoutiq.assess import HIGH
from burnoutiq.loop import BurnoutLoop
from burnoutiq.trajectory import history_features, trajectory_flags

ROOT = Path(__file__).parent
DATA = ROOT / "Datasets" / "burnoutiq_dataset" / "data"
REPORTS = ROOT / "reports"


def _ahead(period: str, k: int) -> list[str]:
    p = pd.Period(period, freq="M")
    return [str(p + i) for i in range(1, k + 1)]


def outcomes(records: pd.DataFrame, period: str) -> pd.DataFrame:
    """Per employee: sustained_ahead / high_next (NaN when the next surveys are not there to judge)."""
    fut = records[records["period"].isin(_ahead(period, 4)) & records["cbi_work_score"].notna()].sort_values("period")
    scores = fut.groupby("employee_id")["cbi_work_score"].agg(list)
    near = set(_ahead(period, 3))
    first_near = fut[fut["period"].isin(near)].groupby("employee_id")["cbi_work_score"].first()

    def sustained(s: list) -> float:
        if len(s) >= 2:
            return float(s[0] >= HIGH and s[1] >= HIGH)
        if len(s) == 1 and s[0] < HIGH:
            return 0.0
        return np.nan
    return pd.DataFrame({"sustained_ahead": scores.map(sustained), "high_next": (first_near >= HIGH).astype(float)})


def _metrics(flag: pd.Series, y: pd.Series) -> dict:
    ok = y.notna()
    f, t = flag[ok].astype(bool), y[ok].astype(bool)
    tp, fp, fn = int((f & t).sum()), int((f & ~t).sum()), int((~f & t).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if prec == prec and rec == rec and prec + rec else float("nan")
    return {"flag_rate": round(100 * float(flag.mean()), 1), "precision": round(100 * prec, 1), "recall": round(100 * rec, 1),
            "f1": round(100 * f1, 1), "true_positives": tp, "false_alarms": fp, "missed": fn, "judged": int(ok.sum())}


def build_rows(loop: BurnoutLoop) -> pd.DataFrame:
    """One row per employee-month with every rule's flag, the learned-model features and both outcomes."""
    rec = loop.records
    out = []
    for period in loop.periods[3:-2]:           # 3 months of history behind, at least 2 months ahead
        cur = loop.run(period).employees[["employee_id", "reference_flag"]].rename(columns={"reference_flag": "current"})
        tr = trajectory_flags(history_features(rec, period), loop.rci)
        rows = tr.merge(cur, on="employee_id", how="left").merge(outcomes(rec, period), left_on="employee_id",
                                                                   right_index=True, how="left")
        rows["period"] = period
        out.append(rows)
    df = pd.concat(out, ignore_index=True)
    df["current"] = df["current"].fillna(False).astype(bool)
    df["one_month"] = df["score_now"] >= HIGH
    df["trajectory"] = (df["sustained_high"] | df["reliable_rise"]).fillna(False).astype(bool)
    df["trajectory_plus"] = df["trajectory_flag"].astype(bool)
    return df


FEATURES = {
    "this month only": ["score_now"],
    "+ trajectory": ["score_now", "prev_score", "baseline", "change_vs_baseline", "high_last3"],
    "+ missed surveys": ["score_now", "prev_score", "baseline", "change_vs_baseline", "high_last3",
                         "answered_now", "missed_last3", "missed_streak", "latest_known"],
}


def learned(df: pd.DataFrame, test_ids: set, target: str = "sustained_ahead") -> dict:
    d = df[df[target].notna()].copy()
    is_test = d["employee_id"].isin(test_ids)
    res = {}
    for name, cols in FEATURES.items():
        x = d[cols].astype(float)
        x = x.fillna(x[~is_test].median())     # imputation learned on training employees only
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        model.fit(x[~is_test], d.loc[~is_test, target])
        p = model.predict_proba(x[is_test])[:, 1]
        y = d.loc[is_test, target]
        res[name] = {"average_precision": round(float(average_precision_score(y, p)), 3),
                     "roc_auc": round(float(roc_auc_score(y, p)), 3)}
    res["base_rate"] = round(float(d.loc[is_test, target].mean()), 3)
    return res


def main() -> dict:
    loop = BurnoutLoop.from_csv(DATA / "employees.csv", DATA / "assessments.csv", DATA / "interventions.csv").fit()
    df = build_rows(loop)
    test = df[df["employee_id"].isin(loop.model.test_employees)]
    rules = {"current": "current rule", "one_month": "one month >= 50", "trajectory": "trajectory",
             "trajectory_plus": "trajectory + missed surveys"}
    result = {"held_out_employees": int(test["employee_id"].nunique()), "employee_months": int(len(test)),
              "periods": [df["period"].min(), df["period"].max()], "rci": round(loop.rci, 1),
              "non_responding_months": int((~test["answered_now"]).sum()), "rules": {}}
    for target in ("sustained_ahead", "high_next"):
        result["rules"][target] = {label: _metrics(test[col], test[target]) for col, label in rules.items()}
    # of the people who did not answer this month and turned out to be burned out, who was caught?
    silent = test[~test["answered_now"]]
    result["silent_positives"] = {label: _metrics(silent[col], silent["sustained_ahead"]) for col, label in rules.items()}
    result["learned"] = {t: learned(df, loop.model.test_employees, t) for t in ("sustained_ahead", "high_next")}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "detection_metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (REPORTS / "DETECTION_REPORT.md").write_text(report(result), encoding="utf-8")
    return result


def report(r: dict) -> str:
    def table(block: dict) -> str:
        lines = ["| Rule | Flagged (% of people-months) | Precision | Recall | F1 | False alarms | Missed |",
                 "|---|---|---|---|---|---|---|"]
        for name, m in block.items():
            lines.append(f"| {name} | {m['flag_rate']}% | {m['precision']}% | {m['recall']}% | {m['f1']} | {m['false_alarms']} | {m['missed']} |")
        return "\n".join(lines)
    lt = ["| Features | Average precision (sustained ahead) | ROC AUC | Average precision (high next) | ROC AUC |", "|---|---|---|---|---|"]
    for name in FEATURES:
        a, b = r["learned"]["sustained_ahead"][name], r["learned"]["high_next"][name]
        lt.append(f"| {name} | {a['average_precision']} | {a['roc_auc']} | {b['average_precision']} | {b['roc_auc']} |")
    return f"""# Detection report: trajectory and missed surveys vs the current rule

Generated by `evaluate_detection.py`. Held-out employees only ({r['held_out_employees']} people, {r['employee_months']} employee-months,
{r['periods'][0]} to {r['periods'][1]}); {r['non_responding_months']} of those months had no survey answer. Reliable change index: {r['rci']} points.

Outcome **sustained ahead**: the next two answered surveys are both >= 50 (burnout that persists).
Outcome **high next**: the next answered survey within 3 months is >= 50.
Precision = share of flags that were right; recall = share of burned-out people who were flagged.

## Sustained ahead (primary)

{table(r['rules']['sustained_ahead'])}

## High next

{table(r['rules']['high_next'])}

## People who skipped this month's survey and were burned out afterwards

{table(r['silent_positives'])}

## Does the history add signal? (logistic regression, trained on other employees)

{chr(10).join(lt)}

Base rate (sustained ahead): {r['learned']['sustained_ahead']['base_rate']}; (high next): {r['learned']['high_next']['base_rate']}.

## Caveats

- Synthetic data. The generator makes people with higher latent burnout less likely to answer surveys, which is
  why missed surveys carry signal here. A real pilot has to confirm this before the rule is trusted.
- Outcomes can only be judged for people who answer later surveys; people who never answer again are not counted.
- These are detection rules for prioritising a check-in, not a diagnosis.
"""


if __name__ == "__main__":
    res = main()
    for target, block in res["rules"].items():
        print(target)
        for name, m in block.items():
            print(f"  {name:28s} flagged {m['flag_rate']:5.1f}%  precision {m['precision']:5.1f}%  recall {m['recall']:5.1f}%  F1 {m['f1']}")
    print("silent this month, sustained ahead:")
    for name, m in res["silent_positives"].items():
        print(f"  {name:28s} recall {m['recall']}%  ({m['true_positives']} of {m['true_positives'] + m['missed']})")
    print("learned:", json.dumps(res["learned"], indent=1))
