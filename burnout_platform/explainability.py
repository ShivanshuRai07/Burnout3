"""Explainability module for the Burnout Platform.

Computes explainability values and creates visualizations.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False
    shap = None


def generate_shap_explanations(
    model, 
    X_test_transformed: np.ndarray, 
    feature_names: np.ndarray, 
    output_dir: Path
) -> None:
    if not HAS_SHAP or shap is None:
        print("Note: SHAP is not installed in the current environment; skipping SHAP plot generation.")
        return

    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test_transformed)
    except Exception:
        sample_n = min(100, len(X_test_transformed))
        explainer = shap.KernelExplainer(model.predict, shap.sample(X_test_transformed, sample_n))
        shap_values = explainer.shap_values(X_test_transformed[:sample_n])
        X_test_transformed = X_test_transformed[:sample_n]
        
    plt.figure(figsize=(8, 6))
    shap.summary_plot(
        shap_values, 
        X_test_transformed, 
        feature_names=feature_names, 
        show=False, 
        max_display=12
    )
    plt.tight_layout()
    plt.savefig(output_dir / "shap_summary.png", dpi=180, bbox_inches="tight")
    plt.close()
