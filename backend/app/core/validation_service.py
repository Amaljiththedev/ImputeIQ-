"""
app/core/validation_service.py

Lightweight Data Validation & Preprocessing Layer executed BEFORE statistical diagnosis.
This module profiles raw CSV datasets, identifies candidate placeholder missing values
(e.g., 0 in BMI/Glucose, -999, "Unknown"), queries Gemini for semantic validation,
and caches decisions in SQLite so repeated inspections run instantly without API overhead.

Why this module is necessary:
- Downstream statistical diagnosis (diagnose_mechanism.py) and imputation strictly require
  missing values to be represented as standard np.nan / nulls.
- Real-world datasets (such as Pima Indians Diabetes) frequently encode missingness using
  valid numbers or strings (0, -999, "Unknown").
- By keeping validation decoupled, no downstream statistical/ML code is modified, preserving
  the integrity and testability of the academic pipeline while solving hidden missingness.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
import numpy as np
import pandas as pd
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.llm_explainer import GEMINI_MODEL
from app.models.db_models import ValidationDecisionCache

logger = logging.getLogger(__name__)


class GeminiValidationDecision(BaseModel):
    """Structured response required from Gemini for semantic placeholder evaluation."""
    column: str
    placeholder: bool
    placeholder_value: Any
    confidence: float
    reason: str
    action: str  # "replace_with_nan" or "keep"
    source: str = "gemini"  # "gemini" or "heuristic_fallback"


def _get_genai_client() -> Any:
    """Retrieves the Google GenAI client initialized with GEMINI_API_KEY."""
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)


def profile_and_detect_placeholders(
    storage_path: str,
    db: Session,
    dataset_id: str,
) -> dict[str, Any]:
    """
    Inspects raw CSV data to produce statistical column profiles and detects potential
    placeholder values (e.g., 0, -999, "Unknown"). Uses Gemini + DB cache to semantically
    determine if each candidate placeholder is biologically/domain valid or should be
    converted to NaN.

    Never modifies values in this step (profiling and detection only).
    """
    df = pd.read_csv(storage_path, sep=None, engine="python")

    row_count = len(df)
    column_count = len(df.columns)
    duplicate_count = int(df.duplicated().sum()) if row_count > 0 else 0

    profiles: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    # Common string/numeric sentinels tested across datasets
    numeric_sentinels = [-999, 999, -99, -1]
    string_sentinels = ["unknown", "n/a", "na", "null", "none", "?"]

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)

        null_cnt = int(series.isna().sum())
        # Safe count of exact zeros for numeric columns
        if pd.api.types.is_numeric_dtype(series):
            zero_cnt = int((series == 0).sum())
        else:
            zero_cnt = 0

        # Safe count of empty or whitespace-only strings for categorical columns
        if pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series):
            str_series = series.dropna().astype(str).str.strip()
            empty_str_cnt = int((str_series == "").sum())
        else:
            empty_str_cnt = 0

        unique_cnt = int(series.nunique(dropna=True))

        min_val = None
        max_val = None
        mean_val = None
        median_val = None
        std_val = None

        if pd.api.types.is_numeric_dtype(series):
            valid_nums = series.dropna()
            if len(valid_nums) > 0:
                min_val = float(valid_nums.min()) if np.isfinite(valid_nums.min()) else None
                max_val = float(valid_nums.max()) if np.isfinite(valid_nums.max()) else None
                mean_val = float(valid_nums.mean()) if np.isfinite(valid_nums.mean()) else None
                median_val = float(valid_nums.median()) if np.isfinite(valid_nums.median()) else None
                std_val = float(valid_nums.std()) if np.isfinite(valid_nums.std()) and len(valid_nums) > 1 else 0.0

        profiles.append({
            "column": col,
            "dtype": dtype_str,
            "min": min_val,
            "max": max_val,
            "mean": round(mean_val, 4) if mean_val is not None else None,
            "median": round(median_val, 4) if median_val is not None else None,
            "std": round(std_val, 4) if std_val is not None else None,
            "unique_count": unique_cnt,
            "null_count": null_cnt,
            "zero_count": zero_cnt,
            "empty_string_count": empty_str_cnt,
        })

        # ── Placeholder Candidate Identification ─────────────────────────────────
        suspicious_values: list[Any] = []

        if pd.api.types.is_numeric_dtype(series):
            # Check 0 candidate if present
            if zero_cnt > 0:
                suspicious_values.append((0, zero_cnt))
            # Check other numeric sentinels
            for s_val in numeric_sentinels:
                cnt = int((series == s_val).sum())
                if cnt > 0:
                    suspicious_values.append((s_val, cnt))
        else:
            # Check string candidates
            str_clean = series.dropna().astype(str).str.strip().str.lower()
            if empty_str_cnt > 0:
                suspicious_values.append(("", empty_str_cnt))
            for s_val in string_sentinels:
                cnt = int((str_clean == s_val).sum())
                if cnt > 0:
                    suspicious_values.append((s_val, cnt))

        # Evaluate suspicious candidates via Cache + Gemini
        for val, cnt in suspicious_values:
            cache_key = f"{col.lower()}:{str(val).lower()}:{dtype_str}"
            cached = db.query(ValidationDecisionCache).filter(ValidationDecisionCache.cache_key == cache_key).first()

            if cached:
                logger.info("Validation decision cache hit for %s -> %s (source: %s)", cache_key, cached.action, getattr(cached, "source", "gemini"))
                candidates.append({
                    "column": col,
                    "placeholder_value": val,
                    "count": cnt,
                    "placeholder": cached.placeholder,
                    "recommendation": "Convert to NaN" if cached.action == "replace_with_nan" else "Keep",
                    "confidence": cached.confidence,
                    "reason": cached.reason,
                    "action": cached.action,
                    "source": getattr(cached, "source", "gemini"),
                })
            else:
                decision = _evaluate_placeholder_with_gemini(col, val, cnt, dtype_str, min_val, max_val, zero_cnt, null_cnt)
                
                # Store decision in cache
                cache_entry = ValidationDecisionCache(
                    cache_key=cache_key,
                    column_name=col,
                    placeholder_value=str(val),
                    placeholder=decision.placeholder,
                    confidence=decision.confidence,
                    reason=decision.reason,
                    action=decision.action,
                    source=decision.source,
                )
                db.add(cache_entry)
                db.commit()

                candidates.append({
                    "column": col,
                    "placeholder_value": val,
                    "count": cnt,
                    "placeholder": decision.placeholder,
                    "recommendation": "Convert to NaN" if decision.action == "replace_with_nan" else "Keep",
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "action": decision.action,
                    "source": decision.source,
                })

    return {
        "dataset_id": dataset_id,
        "row_count": row_count,
        "column_count": column_count,
        "duplicate_count": duplicate_count,
        "profiles": profiles,
        "candidates": candidates,
    }


def _evaluate_placeholder_with_gemini(
    column: str,
    val: Any,
    count: int,
    dtype_str: str,
    min_val: float | None,
    max_val: float | None,
    zero_cnt: int,
    null_cnt: int,
) -> GeminiValidationDecision:
    """
    Calls Gemini to semantically evaluate if `val` in `column` is a valid domain measurement
    or a placeholder for missing data. Includes 3-attempt exponential backoff and fallback heuristics.
    """
    prompt = f"""Dataset Domain: Healthcare / General Data
Column: {column}
Statistics: dtype={dtype_str}, min={min_val}, max={max_val}, zero_count={zero_cnt}, null_count={null_cnt}, candidate_placeholder_value={repr(val)} (count={count})

Question: Can {repr(val)} be a biologically/domain valid value for this variable? Should {repr(val)} be treated as a missing placeholder?

Respond ONLY with structured JSON matching the requested schema."""

    last_exc = None
    for attempt in range(1, 4):
        try:
            client = _get_genai_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": GeminiValidationDecision,
                    "temperature": 0.1,
                },
            )
            data = json.loads(response.text)
            if "source" not in data:
                data["source"] = "gemini"
            return GeminiValidationDecision(**data)
        except Exception as exc:
            last_exc = exc
            logger.warning("Gemini validation call attempt %d failed for column '%s' (%s)", attempt, column, exc)
            if attempt < 3:
                time.sleep(2 ** attempt)

    logger.warning("Gemini validation failed after 3 attempts for column '%s' (%s), using domain fallback.", column, last_exc)
    col_lower = column.lower()
    val_str = str(val).lower()

    # Domain fallback for common healthcare & sentinel placeholders
    if val == 0 or val_str == "0":
        if any(k in col_lower for k in ["bmi", "glucose", "bloodpressure", "bp", "insulin", "skinthickness", "age", "weight", "height", "cholesterol"]):
            return GeminiValidationDecision(
                column=column,
                placeholder=True,
                placeholder_value=val,
                confidence=0.99,
                reason=f"{column} cannot be zero in biological adults or subjects; zero represents missing data.",
                action="replace_with_nan",
                source="heuristic_fallback",
            )
        elif any(k in col_lower for k in ["pregnanc", "child", "visit", "default", "count", "num", "idx", "id"]):
            return GeminiValidationDecision(
                column=column,
                placeholder=False,
                placeholder_value=val,
                confidence=0.98,
                reason=f"Zero is a legitimate count or identifier for {column}.",
                action="keep",
                source="heuristic_fallback",
            )

    if val in [-999, 999, -99, -1] or val_str in ["unknown", "n/a", "na", "null", "none", "?"] or val_str == "":
        return GeminiValidationDecision(
            column=column,
            placeholder=True,
            placeholder_value=val,
            confidence=0.95,
            reason=f"'{val}' is a standard sentinel value indicating missing or unknown data.",
            action="replace_with_nan",
            source="heuristic_fallback",
        )

    return GeminiValidationDecision(
        column=column,
        placeholder=False,
        placeholder_value=val,
        confidence=0.85,
        reason=f"No strong domain evidence that '{val}' is a placeholder in '{column}'; retaining original value.",
        action="keep",
        source="heuristic_fallback",
    )
