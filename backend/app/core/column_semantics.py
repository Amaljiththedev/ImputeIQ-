"""
app/core/column_semantics.py

Classifies dataframe columns into distinct semantic roles:
- IDENTIFIER: Primary/foreign keys, patient/practice IDs, unique sequence numbers.
- CATEGORICAL: Discrete codes, CPRD lookup mappings (`Lookup *.txt`), medical/status flags, or low-cardinality integers/text.
- CONTINUOUS: Quantitative measurements, `DECIMAL` floats, high-cardinality continuous integers (`INTEGER`).

Leverages both CPRD (Clinical Practice Research Datalink) specification type hints (`TEXT`, `INTEGER`, `DECIMAL`, `Lookup *.txt`)
and empirical dataframe statistics.

NOTE: CPRD Aurum column names are concatenated without underscores
(e.g. `probobsid`, `patienttypeid`, `medcodeid`), so all naming-pattern
matching below is done with plain substring/suffix checks (no `_id`,
`_type` boundary requirements) and falls back to an EXPLICIT, spec-derived
allowlist rather than generic keyword guessing wherever possible.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import pandas as pd

logger = logging.getLogger(__name__)


class SemanticRole(str, Enum):
    IDENTIFIER = "identifier"
    CATEGORICAL = "categorical"
    CONTINUOUS = "continuous"


CPRD_KNOWN_IDENTIFIERS = {
    "patid", "pracid", "staffid", "consid", "obsid", "issueid",
    "usualgpstaffid", "parentobsid", "probobsid", "parentprobobsid",
    "lastrevstaffid", "drugrecid", "conssourceid", "refsourceorgid",
    "reftargetorgid", "consmedcodeid",
    "id", "linkid", "emaid", "immid", "referid", "testid", "therapyid",
    "practiceid",
}

CPRD_KNOWN_CATEGORIES = {
    "gender", "patienttypeid", "region", "jobcatid", "cprdconstype",
    "obstypeid", "numunitid", "quantunitid", "refurgencyid",
    "refservicetypeid", "refmodeid", "parentprobrelid", "probstatusid",
    "signid", "emiscodecategoryid", "medcodeid", "prodcodeid",
    "dosageid",
    "medcode", "prodcode", "constype", "enttype", "readcode", "icd", "opcs",
    "sex", "smoking_status", "status", "type", "flag", "cat", "category",
    "source", "role",
}

KNOWN_CONTINUOUS_KEYWORDS = {
    "age", "bmi", "weight", "height", "bp", "systolic", "diastolic",
    "glucose", "dose", "qty", "quantity", "numdays", "duration", "score",
    "value", "visits", "charge", "cost", "revenue", "rate", "estnhscost",
    "numrangelow", "numrangehigh",
}

CPRD_KNOWN_DATE_COLUMNS = {
    "yob", "mob", "emisddate", "regstartdate", "regenddate", "cprdddate",
    "lcd", "uts", "consdate", "enterdate", "obsdate", "issuedate",
    "probenddate", "lastrevdate",
}


@dataclass
class ColumnSemanticInfo:
    column_name: str
    role: SemanticRole
    role_str: str = field(init=False)
    cprd_type_hint: str | None = None
    lookup_file: str | None = None
    rationale: str = ""
    is_cprd_known: bool = False

    def __post_init__(self):
        self.role_str = self.role.value if isinstance(self.role, SemanticRole) else str(self.role)


def classify_column_semantics(
    df: pd.DataFrame,
    column: str,
    cprd_spec: dict[str, Any] | None = None,
) -> ColumnSemanticInfo:
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found in DataFrame.")

    series = df[column]
    series_clean = series.dropna()
    row_count = len(df)
    n_unique = int(series_clean.nunique()) if len(series_clean) > 0 else 0
    unique_ratio = (n_unique / len(series_clean)) if len(series_clean) > 0 else 0.0

    spec_info = cprd_spec.get(column, {}) if cprd_spec and isinstance(cprd_spec, dict) else {}
    if isinstance(spec_info, str):
        cprd_type_hint = spec_info.strip()
        lookup_file = _extract_lookup_file(cprd_type_hint)
    elif isinstance(spec_info, dict):
        cprd_type_hint = spec_info.get("type", spec_info.get("cprd_type"))
        lookup_file = spec_info.get("lookup_file") or _extract_lookup_file(str(cprd_type_hint or ""))
    else:
        cprd_type_hint = None
        lookup_file = None

    col_lower = column.lower().strip()

    if col_lower in CPRD_KNOWN_IDENTIFIERS or (
        col_lower == "id" and unique_ratio > 0.9
    ):
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.IDENTIFIER,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Column matches explicit CPRD identifier allowlist ('{column}').",
            is_cprd_known=True,
        )

    if col_lower.endswith("id") and col_lower not in CPRD_KNOWN_CATEGORIES:
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.IDENTIFIER,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Column name ends in 'id' and is not a known categorical/lookup code ('{column}').",
            is_cprd_known=False,
        )

    if col_lower in CPRD_KNOWN_CATEGORIES:
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CATEGORICAL,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Column matches explicit CPRD categorical/lookup allowlist ('{column}').",
            is_cprd_known=True,
        )

    if col_lower in CPRD_KNOWN_DATE_COLUMNS:
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CATEGORICAL,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Column is a date/temporal field ('{column}'); excluded from continuous imputation.",
            is_cprd_known=True,
        )

    if lookup_file or (cprd_type_hint and "LOOKUP" in str(cprd_type_hint).upper()):
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CATEGORICAL,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file or "Lookup mapping",
            rationale=f"CPRD specification indicates a categorical lookup mapping ({lookup_file or cprd_type_hint}).",
            is_cprd_known=True,
        )

    if cprd_type_hint:
        hint_upper = str(cprd_type_hint).upper()
        if "DECIMAL" in hint_upper or "FLOAT" in hint_upper:
            return ColumnSemanticInfo(
                column_name=column,
                role=SemanticRole.CONTINUOUS,
                cprd_type_hint=cprd_type_hint,
                lookup_file=lookup_file,
                rationale=f"CPRD type hint '{cprd_type_hint}' designates a continuous/decimal quantity.",
                is_cprd_known=True,
            )
        elif "INTEGER" in hint_upper:
            if any(k in col_lower for k in KNOWN_CONTINUOUS_KEYWORDS):
                return ColumnSemanticInfo(
                    column_name=column,
                    role=SemanticRole.CONTINUOUS,
                    cprd_type_hint=cprd_type_hint,
                    lookup_file=lookup_file,
                    rationale=f"CPRD INTEGER type with continuous/count keyword ('{column}').",
                    is_cprd_known=True,
                )
            elif n_unique <= 25 or unique_ratio < 0.05:
                return ColumnSemanticInfo(
                    column_name=column,
                    role=SemanticRole.CATEGORICAL,
                    cprd_type_hint=cprd_type_hint,
                    lookup_file=lookup_file,
                    rationale=f"CPRD INTEGER type with discrete low cardinality ({n_unique} unique values).",
                    is_cprd_known=True,
                )
            else:
                return ColumnSemanticInfo(
                    column_name=column,
                    role=SemanticRole.CONTINUOUS,
                    cprd_type_hint=cprd_type_hint,
                    lookup_file=lookup_file,
                    rationale=f"CPRD INTEGER type with high cardinality ({n_unique} unique values) treated as continuous.",
                    is_cprd_known=True,
                )
        elif "TEXT" in hint_upper:
            if n_unique > 0 and unique_ratio > 0.95 and n_unique > 100:
                return ColumnSemanticInfo(
                    column_name=column,
                    role=SemanticRole.IDENTIFIER,
                    cprd_type_hint=cprd_type_hint,
                    lookup_file=lookup_file,
                    rationale="CPRD TEXT column with >95% unique entries treated as identifier key.",
                    is_cprd_known=True,
                )
            else:
                return ColumnSemanticInfo(
                    column_name=column,
                    role=SemanticRole.CATEGORICAL,
                    cprd_type_hint=cprd_type_hint,
                    lookup_file=lookup_file,
                    rationale=f"CPRD TEXT column treated as categorical ({n_unique} unique entries).",
                    is_cprd_known=True,
                )

    if any(k in col_lower for k in KNOWN_CONTINUOUS_KEYWORDS):
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CONTINUOUS,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Column matches continuous measurement keyword ('{column}').",
            is_cprd_known=False,
        )

    if pd.api.types.is_numeric_dtype(series):
        if n_unique <= 20 and (unique_ratio < 0.10 or row_count <= 50):
            return ColumnSemanticInfo(
                column_name=column,
                role=SemanticRole.CATEGORICAL,
                cprd_type_hint=cprd_type_hint,
                lookup_file=lookup_file,
                rationale=f"Empirical low-cardinality numeric data ({n_unique} distinct values) treated as categorical code/flag.",
                is_cprd_known=False,
            )
        if pd.api.types.is_float_dtype(series):
            return ColumnSemanticInfo(
                column_name=column,
                role=SemanticRole.CONTINUOUS,
                cprd_type_hint=cprd_type_hint,
                lookup_file=lookup_file,
                rationale="Empirical float/decimal data distribution treated as continuous measurement.",
                is_cprd_known=False,
            )
        if unique_ratio > 0.95 and n_unique > 50:
            return ColumnSemanticInfo(
                column_name=column,
                role=SemanticRole.IDENTIFIER,
                cprd_type_hint=cprd_type_hint,
                lookup_file=lookup_file,
                rationale=f"Empirical near-unique integer values ({n_unique} distinct, {unique_ratio:.2f} ratio) treated as identifier.",
                is_cprd_known=False,
            )
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CONTINUOUS,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale=f"Empirical integer data with high cardinality ({n_unique} values) treated as continuous quantity.",
            is_cprd_known=False,
        )

    if pd.api.types.is_bool_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.CATEGORICAL,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale="Empirical boolean or categorical data type.",
            is_cprd_known=False,
        )

    if unique_ratio > 0.95 and n_unique > 50:
        return ColumnSemanticInfo(
            column_name=column,
            role=SemanticRole.IDENTIFIER,
            cprd_type_hint=cprd_type_hint,
            lookup_file=lookup_file,
            rationale="High-cardinality string/object column treated as unique identifier.",
            is_cprd_known=False,
        )

    return ColumnSemanticInfo(
        column_name=column,
        role=SemanticRole.CATEGORICAL,
        cprd_type_hint=cprd_type_hint,
        lookup_file=lookup_file,
        rationale=f"String/object column with discrete values ({n_unique} distinct values) classified as categorical.",
        is_cprd_known=False,
    )


def classify_dataset_semantics(
    df: pd.DataFrame,
    cprd_spec: dict[str, Any] | None = None,
) -> dict[str, ColumnSemanticInfo]:
    return {col: classify_column_semantics(df, col, cprd_spec=cprd_spec) for col in df.columns}


def get_columns_by_role(
    df: pd.DataFrame,
    cprd_spec: dict[str, Any] | None = None,
) -> dict[SemanticRole, list[str]]:
    classified = classify_dataset_semantics(df, cprd_spec=cprd_spec)
    grouped: dict[SemanticRole, list[str]] = {
        SemanticRole.IDENTIFIER: [],
        SemanticRole.CATEGORICAL: [],
        SemanticRole.CONTINUOUS: [],
    }
    for col, info in classified.items():
        grouped[info.role].append(col)
    return grouped


def _extract_lookup_file(type_hint: str) -> str | None:
    if not type_hint:
        return None
    match = re.search(r"lookup[\s:\(]+([a-zA-Z0-9_\-\.]+\.txt)", type_hint, re.IGNORECASE)
    if match:
        return match.group(1)
    if "lookup" in type_hint.lower():
        parts = type_hint.split()
        for p in parts:
            if p.lower() != "lookup":
                return p.strip("():,")
        return "Lookup mapping"
    return None
