"""Stage 5 - Verify: classify the change between a before and an after score.

Two thresholds:
  * practical: |change| >= 5 CBI points counts as improved / worsened, otherwise no change
  * reliable:  |change| >= reliable change index (Jacobson & Truax, 1991), i.e. larger than measurement noise
               RCI threshold = 1.96 * sqrt(2) * SD * sqrt(1 - reliability)

These are observed changes, not causal effects of the intervention.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

PRACTICAL_CHANGE = 5.0


def reliable_change_threshold(sd: float, reliability: float) -> float:
    if not (sd > 0) or not (0 < reliability < 1):
        return float("nan")
    return 1.96 * math.sqrt(2) * sd * math.sqrt(1 - reliability)


def classify_change(change: pd.Series, rci: float, practical: float = PRACTICAL_CHANGE) -> pd.DataFrame:
    """Return outcome (improved / no_change / worsened / no_follow_up) and a reliable-change flag."""
    outcome = np.select([change.isna(), change <= -practical, change >= practical],
                        ["no_follow_up", "improved", "worsened"], default="no_change")
    reliable = change.abs() >= rci if rci == rci else pd.Series(False, index=change.index)
    return pd.DataFrame({"outcome": outcome, "reliable_change": reliable & change.notna()}, index=change.index)
