"""Stage 1 - Assess: score the CBI work-related burnout subscale and assign a level.

CBI work subscale (Borritz & Kristensen, 2004): 7 items scored 0/25/50/75/100, item 7 reverse-scored,
scale score = mean of answered items, non-responder if fewer than 4 items answered.
Levels use the conventional CBI threshold (>= 50 "high"); they are operational labels, not a diagnosis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from burnoutiq.schema import CBI_ITEMS

HIGH = 50.0
VERY_HIGH = 65.0
MIN_ITEMS = 4

# Short wording of the 7 work-subscale questions, all phrased in the burnout direction (item 7 reversed)
CBI_QUESTIONS = {
    "cbi_w1": "Work is emotionally exhausting",
    "cbi_w2": "Burnt out because of work",
    "cbi_w3": "Work is frustrating",
    "cbi_w4": "Worn out at the end of the day",
    "cbi_w5": "Exhausted in the morning at the thought of work",
    "cbi_w6": "Every working hour is tiring",
    "cbi_w7": "Not enough energy for family and friends",
}


def item_scores(row: pd.Series) -> list[dict]:
    """One month's answers as 0-100 burnout-direction scores (None if unanswered), with question text."""
    out = []
    for col, text in CBI_QUESTIONS.items():
        v = pd.to_numeric(row.get(col), errors="coerce")
        if col == "cbi_w7" and pd.notna(v):
            v = 100 - v
        out.append({"item": col, "question": text, "score": None if pd.isna(v) else float(v)})
    return out


def score_cbi(items: pd.DataFrame) -> pd.Series:
    """Item columns cbi_w1..cbi_w7 (item 7 stored as answered) -> scale score, NaN if < 4 answered."""
    scored = items[CBI_ITEMS].apply(pd.to_numeric, errors="coerce")
    scored["cbi_w7"] = 100 - scored["cbi_w7"]
    answered = scored.notna().sum(axis=1)
    return scored.mean(axis=1).where(answered >= MIN_ITEMS).round(2)


def level(score: pd.Series) -> pd.Series:
    return pd.Series(np.select([score >= VERY_HIGH, score >= HIGH, score.notna()],
                               ["very_high", "high", "normal"], default="no_score"), index=score.index)


def cronbach_alpha(items: pd.DataFrame) -> float:
    scored = items[CBI_ITEMS].apply(pd.to_numeric, errors="coerce")
    scored["cbi_w7"] = 100 - scored["cbi_w7"]
    scored = scored.dropna()
    k = scored.shape[1]
    if len(scored) < 10:
        return float("nan")
    return float(k / (k - 1) * (1 - scored.var(ddof=1).sum() / scored.sum(axis=1).var(ddof=1)))
