"""Tests for the Academic Librarian CBI Loader and Data Quality Checks.

Verifies:
- Input path resolution from project root
- Answer parsing and mapping to 0..100 points
- Reverse scoring of CBI item 7 exactly once
- Score computation agreement and boundary conditions (0..100)
- Source consent, eligibility, and completion filters
- Reporting of sample sizes, duplicates, and missing values
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from load_real_cbi import (
    locate_input,
    parse_cbi_answer,
    cronbach_alpha,
    process_cbi_workbook,
    main,
    PUBLISHED_REPORTED_SAMPLE_SIZE,
    ITEM_PATTERNS,
)


@pytest.fixture
def raw_cbi_path() -> Path:
    p = locate_input()
    assert p.exists(), f"Raw CBI workbook not found: {p}"
    return p


def test_locate_input_default_and_explicit(raw_cbi_path: Path):
    """Verify locate_input finds default data/raw path and honors explicit path."""
    resolved = locate_input()
    assert resolved.exists()
    assert resolved.suffix.lower() in {".xlsx", ".xlsm"}

    # Explicit existing path
    assert locate_input(str(raw_cbi_path)) == raw_cbi_path

    # Non-existent path raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        locate_input("non_existent_file.xlsx")


def test_parse_cbi_answer():
    """Verify parsing of labelled answers, text answers, numeric codes, and blanks."""
    # Labelled with trailing category code (1..5)
    assert parse_cbi_answer("Never/Almost Never or to A Very Low Degree (1)") == 0.0
    assert parse_cbi_answer("Seldom or to A Low Degree (2)") == 25.0
    assert parse_cbi_answer("Sometimes or Somewhat (3)") == 50.0
    assert parse_cbi_answer("Often or to A High Degree (4)") == 75.0
    assert parse_cbi_answer("Always or to A Very High Degree (5)") == 100.0

    # Plain numeric codes 1..5
    assert parse_cbi_answer("1") == 0.0
    assert parse_cbi_answer("3") == 50.0
    assert parse_cbi_answer("5") == 100.0
    assert parse_cbi_answer(1) == 0.0
    assert parse_cbi_answer(5) == 100.0

    # Plain text responses
    assert parse_cbi_answer("never") == 0.0
    assert parse_cbi_answer("rarely") == 25.0
    assert parse_cbi_answer("sometimes") == 50.0
    assert parse_cbi_answer("often") == 75.0
    assert parse_cbi_answer("always") == 100.0

    # Missing / empty / invalid
    assert np.isnan(parse_cbi_answer(np.nan))
    assert np.isnan(parse_cbi_answer(None))
    assert np.isnan(parse_cbi_answer(""))
    assert np.isnan(parse_cbi_answer("   "))
    assert np.isnan(parse_cbi_answer("not an answer"))


def test_cronbach_alpha():
    """Verify Cronbach's alpha calculation on synthetic test matrix."""
    # Highly correlated items -> high alpha
    rng = np.random.default_rng(42)
    latent = rng.normal(0, 1, size=(100, 1))
    noise = rng.normal(0, 0.2, size=(100, 7))
    matrix = latent + noise
    alpha = cronbach_alpha(matrix)
    assert alpha is not None
    assert alpha > 0.85

    # Degenerate cases
    assert cronbach_alpha(np.array([[1], [2]])) is None  # < 2 columns
    assert cronbach_alpha(np.array([[1, 2]])) is None    # < 2 rows


def test_loader_execution_and_data_quality(raw_cbi_path: Path, tmp_path: Path):
    """Run loader and verify record counts, schema, and data quality checks."""
    out_csv = tmp_path / "processed_cbi.csv"
    rep_dir = tmp_path / "reports"

    status, report = process_cbi_workbook(
        source_path=raw_cbi_path,
        out_path=out_csv,
        report_dir=rep_dir,
        inspect_only=False,
    )

    assert status == 0
    assert out_csv.exists()
    df = pd.read_csv(out_csv)

    # 1. Row counts: 1,836 raw rows filtered to 1,598 eligible
    assert len(df) == 1598
    assert report["source_rows"] == 1836
    assert report["output_rows"] == 1598

    # 2. Key uniqueness
    assert df["assessment_id"].is_unique
    assert df["employee_id"].is_unique

    # 3. All scores and item values within valid bounds
    assert df["cbi_work_score"].notna().all()
    assert df["cbi_work_score"].between(0.0, 100.0).all()
    for item in ITEM_PATTERNS:
        assert item in df.columns
        assert df[item].notna().all()
        assert df[item].isin([0.0, 25.0, 50.0, 75.0, 100.0]).all()

    # 4. Canonical provenance metadata
    assert (df["split"] == "external_test").all()
    assert (df["data_origin"] == "real").all()
    assert (df["source_dataset"] == "kennesaw_academic_librarian_cbi_2018").all()
    assert (df["cbi_items_answered"] == 7).all()

    # 5. Reports generated
    rep_json = rep_dir / f"{out_csv.stem}.report.json"
    rep_md = rep_dir / f"{out_csv.stem}.quality_report.md"
    assert rep_json.exists()
    assert rep_md.exists()

    rep_data = json.loads(rep_json.read_text(encoding="utf-8"))
    assert rep_data["quality_checks"]["score_recomputes_from_items_with_item7_reversed"] is True
    assert rep_data["quality_checks"]["all_scores_between_0_and_100"] is True


def test_item7_reverse_scoring_and_not_reversed_twice(raw_cbi_path: Path, tmp_path: Path):
    """Verify CBI item 7 is reverse-scored exactly once during score computation."""
    out_csv = tmp_path / "cbi_item7_test.csv"
    status, report = process_cbi_workbook(
        source_path=raw_cbi_path,
        out_path=out_csv,
        report_dir=tmp_path,
        inspect_only=False,
    )
    assert status == 0
    df = pd.read_csv(out_csv)

    # Verification 1: Recomputed score using (100 - cbi_w7) exactly matches cbi_work_score
    items_1_to_6 = [f"cbi_w{i}" for i in range(1, 7)]
    recomputed_score = (df[items_1_to_6].sum(axis=1) + (100.0 - df["cbi_w7"])) / 7.0
    max_diff = (recomputed_score.round(2) - df["cbi_work_score"]).abs().max()
    assert max_diff <= 0.01, f"Score formula discrepancy: max diff {max_diff}"

    # Verification 2: cbi_w7 in export is stored in raw answer direction (energy)
    # Energy correlates negatively with negative burnout symptoms (items 1-6 mean)
    items_1_to_6_mean = df[items_1_to_6].mean(axis=1)
    raw_corr = df["cbi_w7"].corr(items_1_to_6_mean)
    assert raw_corr < -0.40, f"Expected negative correlation for raw energy item, got {raw_corr}"

    # If reversed once, (100 - cbi_w7) correlates positively with burnout symptoms
    reversed_corr = (100.0 - df["cbi_w7"]).corr(items_1_to_6_mean)
    assert reversed_corr > 0.40, f"Expected positive correlation for reversed item 7, got {reversed_corr}"

    # Verify report records this
    assert report["score_summary"]["raw_item7_vs_items1to6_mean_correlation"] < 0
    assert report["score_summary"]["cronbach_alpha_complete_rows"] > 0.88


def test_published_sample_size_discrepancy_reported(raw_cbi_path: Path, tmp_path: Path):
    """Verify the 30-row difference vs the published KSU repository N=1,628 is flagged."""
    out_csv = tmp_path / "cbi_discrepancy_test.csv"
    status, report = process_cbi_workbook(
        source_path=raw_cbi_path,
        out_path=out_csv,
        report_dir=tmp_path,
        inspect_only=False,
    )
    assert status == 0
    assert report["published_reported_sample_size"] == PUBLISHED_REPORTED_SAMPLE_SIZE
    assert report["difference_vs_published_reported_sample_size"] == 30
    assert report["quality_checks"]["published_sample_size_reconciles"] is False


def test_cli_inspect_mode():
    """Verify CLI --inspect runs cleanly without writing output files."""
    code = main(["--inspect"])
    assert code == 0
