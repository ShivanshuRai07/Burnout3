"""Privacy safeguards, PII filtering, and data protection module for BurnoutIQ.

Responsibilities:
- Strips sensitive personal identifiers (PII) at ingestion gate
- Enforces cell suppression for small employee groups (k-anonymity, k >= 5)
- Masks employee identifiers in logs and debug outputs
- Provides standardized privacy disclosures and audit notices
"""
from __future__ import annotations

import re
from typing import Any, List, Set, Tuple
import pandas as pd

# Patterns of forbidden sensitive or personal fields
FORBIDDEN_PII_PATTERNS: list[str] = [
    r"^name$", r".*_name$", r"^name_.*", r"^first_?name.*", r"^last_?name.*", r"^full_?name.*",
    r"^email.*", r".*_email.*", r"^e_?mail.*",
    r".*phone.*", r".*mobile.*", r"^cell.*", r"^telephone.*",
    r"^ssn$", r"^social_?security.*", r"^aadhaar.*", r"^pan_?number.*", r"^passport.*",
    r"^national_?id.*", r"^id_?card.*",
    r".*salary.*", r".*compensation.*", r".*wage.*", r".*bank_?account.*", r".*routing_?number.*",
    r"^medical_?.*", r"^diagnosis.*", r"^prescription.*", r"^therapy_?notes.*",
    r"^doctor.*", r"^patient.*", r"^treatment.*",
]

COMPILED_PII_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PII_PATTERNS]

MIN_AGGREGATION_CELL_SIZE = 5  # k-anonymity floor to prevent deanonymization

PRIVACY_DISCLOSURE_NOTICE = (
    "Privacy and Data Protection: BurnoutIQ operates on non-sensitive, operational workplace "
    "telemetry (hours, meetings, workload indexes). Personal identifiers (names, emails, phones, "
    "government IDs), financial records, and medical/therapy data are strictly excluded from "
    "ingestion and model features. Uploaded CSVs are processed in-memory and not shared with "
    "external third parties. Note: Formal legal compliance (GDPR, HIPAA, India DPDP Act) requires "
    "an independent regulatory assessment by the deploying organization."
)


def is_pii_field(column_name: str) -> bool:
    """Check if a column name matches known PII or protected health patterns."""
    clean_name = str(column_name).strip().lower().replace(" ", "_")
    for pattern in COMPILED_PII_PATTERNS:
        if pattern.match(clean_name):
            return True
    return False


def strip_forbidden_pii(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Scan and drop any columns containing sensitive personal identifiers or medical records.
    
    Returns:
        tuple[pd.DataFrame, list[str]]: Sanitized DataFrame and list of stripped column names.
    """
    pii_cols: list[str] = []
    for col in df.columns:
        if is_pii_field(col):
            pii_cols.append(col)

    if pii_cols:
        sanitized_df = df.drop(columns=pii_cols)
    else:
        sanitized_df = df

    return sanitized_df, pii_cols


def mask_employee_id(emp_id: Any) -> str:
    """Mask employee ID for privacy in logs or non-privileged displays."""
    if emp_id is None or pd.isna(emp_id):
        return "EMP-ANONYMOUS"
    s = str(emp_id).strip()
    if len(s) <= 4:
        return f"***{s[-2:]}" if len(s) >= 2 else "***"
    return f"{s[:2]}***{s[-2:]}"


def apply_cell_suppression(count: int, min_k: int = MIN_AGGREGATION_CELL_SIZE) -> bool:
    """Determine whether an aggregate cell should be suppressed to prevent deanonymization."""
    return 0 < count < min_k
