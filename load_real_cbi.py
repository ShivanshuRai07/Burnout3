#!/usr/bin/env python3
"""Load the Academic Librarian CBI workbook into BurnoutIQ's assessment schema.

This version is adapted to the official Qualtrics-style Excel file and is self-contained:
- detects the seven CBI questions even when prefixed by survey instructions;
- parses answers such as "Often or to A High Degree (4)" to 0..100 CBI points;
- reverse-scores CBI item 7 (energy question) for the total score only;
- filters to consented, finished, eligible respondents with at least 4 valid CBI items;
- writes the canonical BurnoutIQ assessment CSV plus JSON and Markdown quality reports;
- does not require generate_burnoutiq.py or a pre-existing data/assessments.csv.

The output is a real, cross-sectional CBI survey dataset, not a company prediction benchmark.
Review the source dataset's terms before any commercial use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

VERSION = "1.2.0"
SOURCE = "kennesaw_academic_librarian_cbi_2018"
# The official KSU repository description reports 1,628 study participants; reconcile against the workbook before publication.
PUBLISHED_REPORTED_SAMPLE_SIZE = 1628
LABEL_METHOD = "CBI work-related subscale, respondent self-report; score >= 50 is an operational label, not a diagnosis"
DEFAULT_INPUT_NAMES = (
    "Academic_Librarian_Burnout_Dataset.xlsx",
    "Academic Librarian Burnout Dataset.xlsx",
)

# Match based on the substantive question text, irrespective of survey prefix/order.
ITEM_PATTERNS = {
    "cbi_w1": r"emotionally\s+exhaust",
    "cbi_w2": r"burnt?\s*out\s+because",
    "cbi_w3": r"work\s+frustrat|frustrat\w*\s+you",
    "cbi_w4": r"worn\s*out\s+at\s+the\s+end",
    "cbi_w5": r"exhausted\s+in\s+the\s+morning",
    "cbi_w6": r"every\s+working\s+hour",
    "cbi_w7": r"enough\s+energy\s+for\s+family",
}

# The source labels include the numeric category in parentheses, with 1=lowest and 5=highest.
TEXT_POINTS = {
    "never/almost never or to a very low degree": 0,
    "never / almost never or to a very low degree": 0,
    "never or almost never": 0,
    "never/almost never": 0,
    "never / almost never": 0,
    "never": 0,
    "seldom or to a low degree": 25,
    "seldom": 25,
    "rarely": 25,
    "sometimes or somewhat": 50,
    "sometimes": 50,
    "somewhat": 50,
    "often or to a high degree": 75,
    "often": 75,
    "to a high degree": 75,
    "always or to a very high degree": 100,
    "always": 100,
    "to a very high degree": 100,
}

CANONICAL_COLUMNS = [
    "assessment_id", "employee_id", "period", "assessment_date", "department", "team_id",
    "job_level", "role_type", "work_mode", "employment_type", "tenure_months",
    "work_hours_per_week", "overtime_hours_per_week", "meeting_hours_per_week",
    "after_hours_messages_per_week", "pto_days_taken", "survey_responded",
    "perceived_workload_1_5", "manager_support_1_5", "job_control_1_5",
    "work_life_balance_1_5", "job_satisfaction_1_5", "stress_level_0_10", "sleep_hours_avg",
    "cbi_w1", "cbi_w2", "cbi_w3", "cbi_w4", "cbi_w5", "cbi_w6", "cbi_w7",
    "cbi_items_answered", "cbi_work_score", "cbi_high_burnout", "intervention_active",
    "active_intervention_type", "split", "data_origin", "source_dataset", "label_method",
]


def norm(value) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def locate_input(explicit: Optional[str] = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
        return p

    search_dirs = [
        Path.cwd() / "data" / "raw",
        Path(__file__).resolve().parent / "data" / "raw",
        Path.cwd() / "Datasets",
        Path(__file__).resolve().parent / "Datasets",
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path.cwd() / "real_sources" / "librarian_cbi",
        Path(__file__).resolve().parent / "real_sources" / "librarian_cbi",
    ]

    for d in search_dirs:
        for name in DEFAULT_INPUT_NAMES:
            p = d / name
            if p.exists() and p.suffix.lower() in {".xlsx", ".xlsm", ".csv"}:
                return p.resolve()

    raise FileNotFoundError(
        "Could not find Academic_Librarian_Burnout_Dataset.xlsx. Put it in data/raw/ "
        "or pass the workbook path via --input."
    )


def load_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    if path.suffix.lower() == ".csv":
        return {"csv": pd.read_csv(path, dtype=object)}
    if path.suffix.lower() == ".xls":
        raise ValueError("Legacy .xls is not supported directly. Save the workbook as .xlsx first.")
    return pd.read_excel(path, sheet_name=None, dtype=object)


def detect_item_columns(columns) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for item, pattern in ITEM_PATTERNS.items():
        matches = [str(c) for c in columns if re.search(pattern, norm(c), flags=re.I)]
        if len(matches) == 1:
            found[item] = matches[0]
        elif len(matches) > 1:
            raise ValueError(f"Ambiguous source columns for {item}: {matches}. Edit ITEM_PATTERNS or map explicitly.")
    return found


def pick_sheet(sheets: Dict[str, pd.DataFrame]) -> Tuple[str, pd.DataFrame, Dict[str, str]]:
    candidates = []
    for name, df in sheets.items():
        mapping = detect_item_columns(df.columns)
        candidates.append((len(mapping), name, df, mapping))
    candidates.sort(key=lambda x: (x[0], len(x[2])), reverse=True)
    if not candidates:
        raise ValueError("No sheets found in workbook.")
    count, name, df, mapping = candidates[0]
    if count != 7:
        found = ", ".join(mapping) or "none"
        raise ValueError(
            f"Could not detect all 7 CBI items in the workbook. Detected {count}/7 ({found}) on sheet {name!r}. "
            "Run with --inspect and confirm the source headers."
        )
    return name, df.copy(), mapping


def find_column(columns, *, exact: Optional[str] = None, patterns=(), required=False) -> Optional[str]:
    norms = {str(c): norm(c) for c in columns}
    if exact:
        hits = [c for c, n in norms.items() if n == norm(exact)]
    else:
        hits = [c for c, n in norms.items() if all(re.search(p, n, flags=re.I) for p in patterns)]
    if len(hits) > 1:
        hits = sorted(hits, key=lambda c: (len(norms[c]), c))
    if hits:
        return hits[0]
    if required:
        raise ValueError(f"Required source column not found: {exact or patterns}")
    return None


def parse_cbi_answer(value) -> float:
    """Return item points in the direction the respondent answered (0..100); NaN if blank/unrecognised."""
    if pd.isna(value) or not str(value).strip():
        return np.nan
    raw = norm(value)
    # The provided workbook stores labels with a trailing numeric code, e.g. (4).
    code_match = re.search(r"\(([1-5])\)\s*$", raw)
    if code_match:
        return float((int(code_match.group(1)) - 1) * 25)
    # Plain numeric answers are only accepted when they are an unambiguous 1..5 code.
    if re.fullmatch(r"[1-5](?:\.0+)?", raw):
        return float((int(float(raw)) - 1) * 25)
    # Also support text-only CBI exports.
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    if raw in TEXT_POINTS:
        return float(TEXT_POINTS[raw])
    return np.nan


def cronbach_alpha(matrix: np.ndarray) -> Optional[float]:
    x = np.asarray(matrix, dtype=float)
    x = x[~np.isnan(x).any(axis=1)]
    if x.shape[0] < 2 or x.shape[1] < 2:
        return None
    total_var = x.sum(axis=1).var(ddof=1)
    if total_var == 0:
        return None
    return float(x.shape[1] / (x.shape[1] - 1) * (1 - x.var(axis=0, ddof=1).sum() / total_var))


def yes_value(series: pd.Series) -> pd.Series:
    return series.map(lambda v: norm(v) in {"yes", "y", "true", "1"})


def bool_value(series: pd.Series) -> pd.Series:
    return series.map(lambda v: norm(v) in {"true", "1", "yes", "finished", "complete", "completed"})


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")[:72] or "unnamed_source_column"


def process_cbi_workbook(
    source_path: Path,
    out_path: Optional[Path] = None,
    report_dir: Optional[Path] = None,
    inspect_only: bool = False,
) -> tuple[int, dict]:
    """Core processing function for the Academic Librarian CBI workbook.
    
    Returns (status_code, report_dict).
    """
    sheets = load_sheets(source_path)
    sheet_name, raw, item_cols = pick_sheet(sheets)

    consent_col = find_column(raw.columns, patterns=(r"online survey consent form|consent",), required=False)
    current_col = find_column(raw.columns, patterns=(r"currently work", r"academic library", r"united states"), required=False)
    degree_col = find_column(raw.columns, patterns=(r"master", r"library science", r"accredited degree"), required=False)
    finished_col = find_column(raw.columns, exact="Finished", required=False)
    progress_col = find_column(raw.columns, patterns=(r"progress",), required=False)
    recorded_col = find_column(raw.columns, patterns=(r"recorded date",), required=False)
    start_col = find_column(raw.columns, patterns=(r"start date",), required=False)
    age_col = find_column(raw.columns, patterns=(r"what is your age",), required=False)
    years_col = find_column(raw.columns, patterns=(r"years have you spent in the profession",), required=False)
    gender_col = find_column(raw.columns, patterns=(r"gender identity",), required=False)

    required_screens = {
        "consent": consent_col,
        "current US academic library work": current_col,
        "MLS/ALA-accredited equivalent degree": degree_col,
        "Finished status": finished_col,
    }
    missing_screens = [name for name, col in required_screens.items() if col is None]
    if missing_screens:
        err_msg = "Cannot safely apply source consent/eligibility filters because columns missing: " + ", ".join(missing_screens)
        print(f"ERROR: {err_msg}", file=sys.stderr)
        return 2, {"error": err_msg}

    numeric = pd.DataFrame(index=raw.index)
    item_coding = {}
    unknown_answers = {}
    for item, col in item_cols.items():
        values = raw[col]
        converted = values.map(parse_cbi_answer).astype(float)
        bad = values.notna() & values.astype(str).str.strip().ne("") & converted.isna()
        if bad.any():
            unknown_answers[item] = sorted(values[bad].astype(str).unique().tolist())[:20]
        numeric[item] = converted
        item_coding[item] = {
            "source_column": col,
            "nonmissing_raw_answers": int(values.notna().sum()),
            "parsed_answers": int(converted.notna().sum()),
            "unknown_nonmissing_answers": int(bad.sum()),
            "score_mapping": "answer choice 1..5 -> 0,25,50,75,100; based on labelled response text",
        }
    if unknown_answers:
        print("ERROR: Some non-empty CBI answers were not recognised; refusing to silently discard them:", file=sys.stderr)
        print(json.dumps(unknown_answers, indent=2), file=sys.stderr)
        return 2, {"error": "unknown_answers", "details": unknown_answers}

    # Keep item 7 in its original answer direction in the data file; reverse it for total-score calculation.
    answer_numeric = numeric.copy()
    score_items = numeric.copy()
    score_items["cbi_w7"] = 100 - score_items["cbi_w7"]
    n_answered = score_items.notna().sum(axis=1)
    score = score_items.mean(axis=1, skipna=True).where(n_answered >= 4).round(2)

    consent_values = raw[consent_col].map(norm)
    consent_yes = consent_values.isin({"i consent, begin the study", "i agree", "yes", "consent"})
    current_yes = yes_value(raw[current_col])
    degree_yes = yes_value(raw[degree_col])
    finished_yes = bool_value(raw[finished_col])
    eligible = consent_yes & current_yes & degree_yes & finished_yes & n_answered.ge(4) & score.notna()

    eligible_counts = {
        "raw_rows": int(len(raw)),
        "explicit_consent_yes": int(consent_yes.sum()),
        "finished_true": int(finished_yes.sum()),
        "current_us_academic_library_yes": int(current_yes.sum()),
        "degree_eligibility_yes": int(degree_yes.sum()),
        "all_7_CBI_items_answered": int(n_answered.eq(7).sum()),
        "at_least_4_CBI_items_answered": int(n_answered.ge(4).sum()),
        "eligible_and_scored_rows_exported": int(eligible.sum()),
    }

    if inspect_only:
        print(f"Source: {source_path}")
        print(f"Sheet: {sheet_name}; rows: {len(raw)}; columns: {len(raw.columns)}")
        print("Detected CBI item columns:")
        for item, col in item_cols.items():
            print(f"  {item}: {col}")
            print("    answers:", raw[col].value_counts(dropna=False).head(10).to_dict())
        print("Screening columns:")
        for name, col in required_screens.items():
            print(f"  {name}: {col}")
        print("Counts:", json.dumps(eligible_counts, indent=2))
        return 0, {"sheet": sheet_name, "counts": eligible_counts, "item_columns": item_cols}

    # Determine output and report paths
    if out_path is None:
        out_path = Path.cwd() / "data" / "processed" / "real_librarian_cbi.csv"
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if report_dir is None:
        report_dir = Path.cwd() / "reports" / "data_quality"
    report_dir = report_dir.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    schema_columns = CANONICAL_COLUMNS

    keep_idx = np.flatnonzero(eligible.to_numpy())
    clean_source = raw.iloc[keep_idx].copy().reset_index(drop=True)
    clean_answers = answer_numeric.iloc[keep_idx].reset_index(drop=True)
    clean_scores = score.iloc[keep_idx].reset_index(drop=True)
    clean_n = n_answered.iloc[keep_idx].reset_index(drop=True)
    clean_dates = pd.to_datetime(clean_source[recorded_col], errors="coerce") if recorded_col else pd.Series(pd.NaT, index=clean_source.index)
    if recorded_col is None and start_col is not None:
        clean_dates = pd.to_datetime(clean_source[start_col], errors="coerce")

    out = pd.DataFrame(index=clean_source.index)
    out["assessment_id"] = [f"R-LIB-{i + 1:05d}" for i in range(len(out))]
    out["employee_id"] = [f"LIB-{i + 1:05d}" for i in range(len(out))]
    out["period"] = clean_dates.dt.strftime("%Y-%m").fillna("2018-04")
    out["assessment_date"] = clean_dates.dt.strftime("%Y-%m-%d")
    out["survey_responded"] = clean_n.gt(0)
    for item in ITEM_PATTERNS:
        out[item] = clean_answers[item].astype(float)
    out["cbi_items_answered"] = clean_n.astype(int)
    out["cbi_work_score"] = clean_scores.astype(float)
    out["cbi_high_burnout"] = (clean_scores >= 50).astype(float)
    out["split"] = "external_test"
    out["data_origin"] = "real"
    out["source_dataset"] = SOURCE
    out["label_method"] = LABEL_METHOD

    for col in schema_columns:
        if col not in out.columns:
            out[col] = np.nan

    out = out.reindex(columns=schema_columns)
    out["source_row_number"] = keep_idx + 2  # Excel row number: header is row 1
    out["consent_response"] = clean_source[consent_col].astype(str).to_numpy()
    out["eligibility_current_us_academic_library"] = clean_source[current_col].astype(str).to_numpy()
    out["eligibility_mls_or_ala_equivalent"] = clean_source[degree_col].astype(str).to_numpy()
    out["source_finished"] = clean_source[finished_col].astype(str).to_numpy()
    if progress_col:
        out["src_progress"] = clean_source[progress_col].to_numpy()
    if age_col:
        out["src_age_band"] = clean_source[age_col].to_numpy()
    if years_col:
        out["src_years_in_profession"] = clean_source[years_col].to_numpy()
    if gender_col:
        out["src_gender_identity"] = clean_source[gender_col].to_numpy()

    used_cols = set(item_cols.values()) | {consent_col, current_col, degree_col, finished_col}
    for c in raw.columns:
        if c in used_cols or c in {age_col, years_col, gender_col, progress_col} or c is None:
            continue
        if c == recorded_col or c == start_col:
            continue
        name = "src_" + slug(str(c))
        if name not in out.columns:
            out[name] = clean_source[c].to_numpy()

    out.to_csv(out_path, index=False)

    complete_items = score_items.iloc[keep_idx].dropna().to_numpy(dtype=float)
    alpha = cronbach_alpha(complete_items)
    raw_item7_corr = float(answer_numeric.loc[eligible, "cbi_w7"].corr(answer_numeric.loc[eligible, [f"cbi_w{i}" for i in range(1, 7)]].mean(axis=1)))
    score_rebuilt = out[[f"cbi_w{i}" for i in range(1, 7)]].copy()
    score_rebuilt["cbi_w7"] = 100 - out["cbi_w7"]
    score_rebuilt = score_rebuilt.mean(axis=1).round(2)
    score_match = bool(np.allclose(score_rebuilt.to_numpy(), out["cbi_work_score"].to_numpy(), atol=0.011, rtol=0))

    date_duplicates = int(clean_source[recorded_col].duplicated().sum()) if recorded_col else None
    stats = out["cbi_work_score"].astype(float).describe()
    report = {
        "loader_version": VERSION,
        "input_file": source_path.name,
        "input_sha256": file_sha256(source_path),
        "source_sheet": sheet_name,
        "output_file": str(out_path),
        "source_rows": int(len(raw)),
        "output_rows": int(len(out)),
        "published_reported_sample_size": PUBLISHED_REPORTED_SAMPLE_SIZE,
        "difference_vs_published_reported_sample_size": int(PUBLISHED_REPORTED_SAMPLE_SIZE - len(out)),
        "consent_column": str(consent_col),
        "eligibility_columns": {
            "currently_works_in_us_academic_library": str(current_col),
            "degree": str(degree_col),
            "finished": str(finished_col),
        },
        "filters_applied": [
            "explicit response indicating consent",
            "currently works in an academic library in the United States = Yes",
            "MLS or equivalent ALA-accredited degree = Yes",
            "Finished = True",
            "at least 4 valid CBI item responses",
        ],
        "row_counts": eligible_counts,
        "item_columns_and_parsing": item_coding,
        "quality_checks": {
            "all_exported_rows_pass_filters": bool(eligible.iloc[keep_idx].all()),
            "unique_assessment_ids": bool(out["assessment_id"].is_unique),
            "unique_synthetic_row_ids": bool(out["employee_id"].is_unique),
            "no_duplicate_full_source_rows": int(raw.duplicated().sum()) == 0,
            "source_duplicate_full_rows": int(raw.duplicated().sum()),
            "published_sample_size_reconciles": int(len(out)) == PUBLISHED_REPORTED_SAMPLE_SIZE,
            "duplicate_recorded_timestamps_in_clean_export": date_duplicates,
            "all_scores_between_0_and_100": bool(out["cbi_work_score"].dropna().between(0, 100).all()),
            "all_item_scores_on_0_25_50_75_100_scale": bool(out[list(ITEM_PATTERNS)].stack().dropna().isin([0, 25, 50, 75, 100]).all()),
            "score_recomputes_from_items_with_item7_reversed": score_match,
            "alpha_calculated_on_complete_item_rows": int(out[[f"cbi_w{i}" for i in range(1, 7)] + ["cbi_w7"]].notna().all(axis=1).sum()),
        },
        "score_summary": {
            "n_scored": int(out["cbi_work_score"].notna().sum()),
            "mean": round(float(stats["mean"]), 3) if len(out) else None,
            "sd": round(float(stats["std"]), 3) if len(out) else None,
            "min": round(float(stats["min"]), 3) if len(out) else None,
            "median": round(float(stats["50%"]), 3) if len(out) else None,
            "max": round(float(stats["max"]), 3) if len(out) else None,
            "pct_score_ge_50": round(float(100 * (out["cbi_work_score"] >= 50).mean()), 2) if len(out) else None,
            "cronbach_alpha_complete_rows": round(alpha, 4) if alpha is not None else None,
            "raw_item7_vs_items1to6_mean_correlation": round(raw_item7_corr, 4) if np.isfinite(raw_item7_corr) else None,
        },
        "interpretation_and_limitations": [
            "The CBI score is computed from the survey responses; it is not an independent label for training a model on those same item responses.",
            "This is one cross-sectional survey of US academic librarians. It does not contain work hours, manager-support, collaboration metadata, or longitudinal follow-up needed to validate workplace early-warning or intervention-effectiveness claims.",
            "The generated employee_id values are row-level pseudonyms created for schema compatibility; this workbook does not supply persistent employee identifiers.",
            "Check the repository's current licence and permission requirements before commercial use.",
        ],
        "unknown_answers": unknown_answers,
    }

    report_path = report_dir / f"{out_path.stem}.report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = report_dir / f"{out_path.stem}.quality_report.md"
    md = [
        "# Academic Librarian CBI import — quality report",
        "",
        f"- Loader version: `{VERSION}`",
        f"- Source workbook: `{source_path.name}` (sheet: `{sheet_name}`)",
        f"- Rows in workbook: **{len(raw):,}**",
        f"- Clean, eligible records exported: **{len(out):,}**",
        f"- Official repository description reports N={PUBLISHED_REPORTED_SAMPLE_SIZE:,}; current export differs by {PUBLISHED_REPORTED_SAMPLE_SIZE - len(out):,} records and needs reconciliation.",
        "",
        "## Checks",
        "",
        f"- Explicit consent recorded: {int(consent_yes.sum()):,}/{len(raw):,}",
        f"- `Finished = True`: {int(finished_yes.sum()):,}/{len(raw):,}",
        f"- Current US academic-library work marked Yes: {int(current_yes.sum()):,}/{len(raw):,}",
        f"- MLS/ALA-equivalent degree marked Yes: {int(degree_yes.sum()):,}/{len(raw):,}",
        f"- All seven CBI items answered: {int(n_answered.eq(7).sum()):,}",
        f"- At least four CBI items answered: {int(n_answered.ge(4).sum()):,}",
        f"- Duplicate complete source rows: {int(raw.duplicated().sum()):,}",
        f"- Score formula verified: **{'PASS' if score_match else 'FAIL'}**",
        f"- Scores within 0–100: **{'PASS' if report['quality_checks']['all_scores_between_0_and_100'] else 'FAIL'}**",
        f"- Item values on 0/25/50/75/100 scale: **{'PASS' if report['quality_checks']['all_item_scores_on_0_25_50_75_100_scale'] else 'FAIL'}**",
        "",
        "## Score summary",
        "",
        f"- Mean: {report['score_summary']['mean']}",
        f"- Standard deviation: {report['score_summary']['sd']}",
        f"- Median: {report['score_summary']['median']}",
        f"- Percentage with score ≥ 50: {report['score_summary']['pct_score_ge_50']}% (operational label only)",
        f"- Cronbach's alpha (complete item responses): {report['score_summary']['cronbach_alpha_complete_rows']}",
        f"- Raw item 7 correlation with items 1–6 mean: {report['score_summary']['raw_item7_vs_items1to6_mean_correlation']} (should usually be negative before reverse-scoring)",
        "",
        "## Important limits",
        "",
        "- This file validates import and CBI score computation. Because the target score is calculated from these same seven CBI items, using those items to predict the score would cause target leakage.",
        "- It has no workplace-system predictors or follow-up outcomes, so it cannot validate workplace-only early-warning, forecasting, or intervention-effectiveness claims.",
        "- The employee IDs in the exported file are generated row IDs, not known persistent employee identities.",
        "- Check the dataset repository's current licence and permission requirements before commercial use.",
        "",
        f"Detailed metrics: `{report_path.name}`",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"Wrote clean dataset: {out_path}")
    print(f"Wrote JSON report: {report_path}")
    print(f"Wrote quality report: {md_path}")
    print(json.dumps({
        "row_counts": eligible_counts,
        "published_reported_sample_size": PUBLISHED_REPORTED_SAMPLE_SIZE,
        "difference_vs_published_reported_sample_size": PUBLISHED_REPORTED_SAMPLE_SIZE - len(out),
        "score_summary": report["score_summary"],
        "quality_checks": report["quality_checks"],
    }, indent=2))

    if len(out) != PUBLISHED_REPORTED_SAMPLE_SIZE:
        print(f"NOTE: KSU repository description reports N={PUBLISHED_REPORTED_SAMPLE_SIZE}; workbook export yielded {len(out)} eligible CBI records. Reconcile this 30-row discrepancy before publication.", file=sys.stderr)

    passed_checks = all([
        report["quality_checks"]["all_exported_rows_pass_filters"],
        report["quality_checks"]["unique_assessment_ids"],
        report["quality_checks"]["unique_synthetic_row_ids"],
        report["quality_checks"]["all_scores_between_0_and_100"],
        report["quality_checks"]["all_item_scores_on_0_25_50_75_100_scale"],
        report["quality_checks"]["score_recomputes_from_items_with_item7_reversed"],
    ])
    if not passed_checks:
        print("WARNING: One or more data checks failed. Inspect the reports before using the output.", file=sys.stderr)
        return 1, report
    return 0, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default=None, help="Workbook path. Defaults to data/raw/Academic_Librarian_Burnout_Dataset.xlsx.")
    parser.add_argument("--input", "-i", dest="explicit_input", default=None, help="Explicit workbook path.")
    parser.add_argument("--out", "-o", default=None, help="Output CSV path (default: data/processed/real_librarian_cbi.csv).")
    parser.add_argument("--report-dir", default=None, help="Report output directory (default: reports/data_quality).")
    parser.add_argument("--inspect", action="store_true", help="Inspect source sheet, item matches, answer values and eligibility counts without exporting.")
    args = parser.parse_args(argv)

    raw_input = args.explicit_input or args.input
    try:
        source = locate_input(raw_input)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else None
    report_dir = Path(args.report_dir) if args.report_dir else None

    status, _ = process_cbi_workbook(
        source_path=source,
        out_path=out_path,
        report_dir=report_dir,
        inspect_only=args.inspect,
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
