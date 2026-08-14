"""
app/core/validation_service.py

Lightweight Data Validation & Preprocessing Layer executed BEFORE statistical diagnosis.
This module profiles raw CSV datasets, identifies candidate placeholder missing values
(e.g., 0 in BMI/Glucose, -999, "Unknown"), asks a language model to validate them semantically,
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
import time
from typing import Any
import numpy as np
import pandas as pd
from pydantic import BaseModel, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.llm_client import complete_json
from app.models.db_models import ValidationDecisionCache

logger = logging.getLogger(__name__)


# How the placeholder stage works, in one sentence, so the interface can state
# it rather than leaving the user to infer it.
DETECTION_METHOD_DESCRIPTION = (
    "Values are screened against a fixed candidate list (0, -999, 999, -99, -1, "
    "'unknown', 'n/a', 'na', 'null', 'none', '?', empty string). Each candidate is "
    "then judged by a language model using only the column name and its summary "
    "statistics, unless you supply a data dictionary, in which case your description "
    "is used instead. Column names can be misleading, so review the assumptions below "
    "before applying any conversion."
)


class ColumnAssumption(BaseModel):
    """The tool's working interpretation of a variable, stated for approval."""
    column: str
    assumed_meaning: str
    plausible_range: str | None = None
    source: str = "language_model"  # user_dictionary | language_model | unavailable
    needs_review: bool = True


class _AssumptionBatch(BaseModel):
    assumptions: list[ColumnAssumption]


def parse_data_dictionary(content: str | None) -> dict[str, str]:
    """Parse a user-supplied data dictionary into {column: description}.

    Accepts JSON mapping column names to descriptions, or plain text with one
    entry per line separated by a colon, comma, tab, dash or equals sign. Kept
    deliberately permissive: data dictionaries come in many shapes and the point
    is to let a user describe their own data, not to impose a schema on them.
    """
    if not content or not content.strip():
        return {}

    text = content.strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in loaded.items() if str(v).strip()}
        if isinstance(loaded, list):
            out: dict[str, str] = {}
            for row in loaded:
                if isinstance(row, dict):
                    name = row.get("column") or row.get("name") or row.get("variable")
                    desc = row.get("description") or row.get("meaning") or row.get("label")
                    if name and desc:
                        out[str(name).strip().lower()] = str(desc).strip()
            if out:
                return out
    except (json.JSONDecodeError, ValueError):
        pass

    parsed: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in (":", "\t", " - ", " = ", "=", ","):
            if sep in line:
                name, _, desc = line.partition(sep)
                if name.strip() and desc.strip():
                    parsed[name.strip().lower()] = desc.strip()
                break
    return parsed


def infer_column_assumptions(
    df: pd.DataFrame,
    user_descriptions: dict[str, str] | None = None,
) -> list[ColumnAssumption]:
    """State what each column is taken to represent, and where that came from.

    A user-supplied description always wins. Anything else is the model's
    interpretation of a name, which is exactly the guess that needs checking,
    so it is returned flagged for review. One batched request covers every
    remaining column rather than one call per column.
    """
    user_descriptions = {k.lower(): v for k, v in (user_descriptions or {}).items()}
    assumptions: list[ColumnAssumption] = []
    needs_inference: list[str] = []

    for col in df.columns:
        described = user_descriptions.get(str(col).strip().lower())
        if described:
            assumptions.append(
                ColumnAssumption(
                    column=col,
                    assumed_meaning=described,
                    plausible_range=None,
                    source="user_dictionary",
                    needs_review=False,
                )
            )
        else:
            needs_inference.append(col)

    if not needs_inference:
        return assumptions

    summary_lines = []
    for col in needs_inference:
        s = df[col]
        bits = [f"dtype={s.dtype}", f"unique={int(s.nunique(dropna=True))}"]
        if pd.api.types.is_numeric_dtype(s):
            valid = s.dropna()
            if not valid.empty:
                bits.append(f"min={valid.min()}")
                bits.append(f"max={valid.max()}")
        else:
            sample = [str(v) for v in s.dropna().unique()[:5]]
            if sample:
                bits.append("examples=" + "|".join(sample))
        summary_lines.append(f"- {col}: " + ", ".join(bits))

    prompt = (
        "For each column below, state in one short sentence what the variable most "
        "likely represents, and give a plausible valid range or set of values.\n"
        "Base this only on the name and statistics given. Where the name is ambiguous, "
        "say so plainly rather than guessing confidently.\n\n"
        + "\n".join(summary_lines)
        + "\n\nRespond ONLY with JSON matching the requested schema."
    )

    try:
        batch = complete_json(prompt, _AssumptionBatch, temperature=0.1)
        inferred = {a.column: a for a in batch.assumptions}
    except Exception as exc:
        logger.warning("Column assumption inference unavailable (%s); reporting as unknown.", exc)
        inferred = {}

    for col in needs_inference:
        got = inferred.get(col)
        if got:
            assumptions.append(
                ColumnAssumption(
                    column=col,
                    assumed_meaning=got.assumed_meaning,
                    plausible_range=got.plausible_range,
                    source="language_model",
                    needs_review=True,
                )
            )
        else:
            assumptions.append(
                ColumnAssumption(
                    column=col,
                    assumed_meaning=(
                        "Not established. No description was supplied and the meaning "
                        "could not be inferred, so placeholder decisions for this column "
                        "rest on its name alone."
                    ),
                    plausible_range=None,
                    source="unavailable",
                    needs_review=True,
                )
            )

    order = {c: i for i, c in enumerate(df.columns)}
    return sorted(assumptions, key=lambda a: order.get(a.column, 0))


ACTION_REPLACE = "replace_with_nan"
ACTION_KEEP = "keep"

# The model is asked for one of two action values but does not reliably return
# the exact literal: observed replies have included "replace_with_null" and
# "fill_with_null", whose meaning is identical. Downstream code compares against
# ACTION_REPLACE exactly, so an unrecognised synonym silently became "keep" and
# the placeholder survived cleaning with the model's own reasoning saying it
# should not have. Answers are normalised on the way in rather than trusting
# free text to match.
_REPLACE_SYNONYMS = {
    "replace_with_nan", "replace_with_null", "replace_with_na", "replace",
    "fill_with_nan", "fill_with_null", "set_to_nan", "set_to_null",
    "convert", "convert_to_nan", "convert_to_null", "nan", "null", "na",
    "treat_as_missing", "mark_missing", "missing",
}
_KEEP_SYNONYMS = {
    "keep", "retain", "keep_value", "keep_as_is", "no_change", "none",
    "valid", "leave", "leave_as_is", "ignore", "do_nothing",
}


def normalise_action(raw: Any) -> str | None:
    """Map a free-text action onto one of the two values the pipeline acts on.

    Returns None when the wording is not recognised, so the caller can decide
    using the model's own placeholder flag instead of silently guessing.
    """
    token = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if token in _REPLACE_SYNONYMS:
        return ACTION_REPLACE
    if token in _KEEP_SYNONYMS:
        return ACTION_KEEP
    return None


class PlaceholderDecision(BaseModel):
    """Structured reply required from the model for semantic placeholder evaluation."""
    column: str
    placeholder: bool
    placeholder_value: Any
    confidence: float
    reason: str
    action: str  # always ACTION_REPLACE or ACTION_KEEP after validation
    source: str = "language_model"  # "language_model" or "heuristic_fallback"

    @model_validator(mode="after")
    def _canonicalise_action(self) -> "PlaceholderDecision":
        resolved = normalise_action(self.action)
        if resolved is None:
            # Unrecognised wording. The model also returns a boolean saying
            # whether this is a placeholder, which is far less prone to
            # paraphrase, so defer to that.
            logger.warning(
                "Unrecognised placeholder action %r for column %r; using placeholder=%s.",
                self.action, self.column, self.placeholder,
            )
            resolved = ACTION_REPLACE if self.placeholder else ACTION_KEEP
        object.__setattr__(self, "action", resolved)
        return self


def profile_and_detect_placeholders(
    storage_path: str,
    db: Session,
    dataset_id: str,
    data_dictionary: str | None = None,
) -> dict[str, Any]:
    """
    Inspects raw CSV data to produce statistical column profiles and detects potential
    placeholder values (e.g., 0, -999, "Unknown"). Uses the language model plus a DB cache to semantically
    determine if each candidate placeholder is biologically/domain valid or should be
    converted to NaN.

    Never modifies values in this step (profiling and detection only).
    """
    df = pd.read_csv(storage_path, sep=None, engine="python")

    row_count = len(df)
    column_count = len(df.columns)
    duplicate_count = int(df.duplicated().sum()) if row_count > 0 else 0

    user_descriptions = parse_data_dictionary(data_dictionary)
    assumptions = infer_column_assumptions(df, user_descriptions)
    assumption_by_col = {a.column: a for a in assumptions}

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

        # Evaluate suspicious candidates via cache, then the model
        col_description = user_descriptions.get(str(col).strip().lower())
        for val, cnt in suspicious_values:
            # A user-supplied description changes the judgement, so it must
            # change the cache key too. Otherwise a decision made from the
            # column name alone would be reused after the user corrected it.
            desc_marker = "userdict" if col_description else "nodict"
            cache_key = f"{col.lower()}:{str(val).lower()}:{dtype_str}:{desc_marker}"
            cached = db.query(ValidationDecisionCache).filter(ValidationDecisionCache.cache_key == cache_key).first()

            if cached:
                # Normalise on read as well as on write. Rows persisted before
                # canonicalisation existed can hold a synonym such as
                # "replace_with_null", and a cache hit would otherwise bypass
                # the validator and reintroduce the bug for every dataset that
                # reuses the entry.
                cached_action = normalise_action(cached.action)
                if cached_action is None:
                    cached_action = ACTION_REPLACE if cached.placeholder else ACTION_KEEP
                logger.info("Validation decision cache hit for %s -> %s (source: %s)", cache_key, cached_action, getattr(cached, "source", "language_model"))
                candidates.append({
                    "column": col,
                    "placeholder_value": val,
                    "count": cnt,
                    "placeholder": cached.placeholder,
                    "recommendation": "Convert to NaN" if cached_action == ACTION_REPLACE else "Keep",
                    "confidence": cached.confidence,
                    "reason": cached.reason,
                    "action": cached_action,
                    "source": getattr(cached, "source", "language_model"),
                })
            else:
                decision = _evaluate_placeholder_semantically(
                    col, val, cnt, dtype_str, min_val, max_val, zero_cnt, null_cnt,
                    column_description=col_description,
                )
                
                # Store decision in cache.
                #
                # cache_key is uniquely indexed, and two requests for the same
                # dataset can be in flight at once (React re-invokes effects in
                # development, and a user can simply reload). Both miss the
                # cache, both call the model, and the second insert violates the
                # constraint. That surfaced in the browser as a CORS error,
                # because an unhandled exception is returned by the outer error
                # middleware which sits outside CORSMiddleware and so carries no
                # headers. Losing the race is harmless: the other request has
                # already stored an equivalent decision, so adopt it.
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
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    winner = (
                        db.query(ValidationDecisionCache)
                        .filter(ValidationDecisionCache.cache_key == cache_key)
                        .first()
                    )
                    if winner is not None:
                        logger.info(
                            "Concurrent validation for %s; using the decision already cached.",
                            cache_key,
                        )
                        resolved = normalise_action(winner.action)
                        if resolved is None:
                            resolved = ACTION_REPLACE if winner.placeholder else ACTION_KEEP
                        decision = PlaceholderDecision(
                            column=col,
                            placeholder=winner.placeholder,
                            placeholder_value=val,
                            confidence=winner.confidence,
                            reason=winner.reason,
                            action=resolved,
                            source=getattr(winner, "source", "language_model"),
                        )

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
        "assumptions": [a.model_dump() for a in assumptions],
        "has_data_dictionary": bool(user_descriptions),
        "detection_method": DETECTION_METHOD_DESCRIPTION,
    }


def _evaluate_placeholder_semantically(
    column: str,
    val: Any,
    count: int,
    dtype_str: str,
    min_val: float | None,
    max_val: float | None,
    zero_cnt: int,
    null_cnt: int,
    column_description: str | None = None,
) -> PlaceholderDecision:
    """
    Asks the model to semantically evaluate if `val` in `column` is a valid domain measurement
    or a placeholder for missing data. Includes 3-attempt exponential backoff and fallback heuristics.

    When the user has described the column, that description is authoritative and
    is given precedence over any inference drawn from the column name.
    """
    described = (
        f"User-supplied description of this column: {column_description}\n"
        "Treat this description as authoritative; it overrides any assumption "
        "you would otherwise make from the column name.\n"
        if column_description
        else "No user description was supplied for this column; you have only its name and statistics.\n"
    )

    prompt = f"""Dataset Domain: Healthcare / General Data
Column: {column}
{described}Statistics: dtype={dtype_str}, min={min_val}, max={max_val}, zero_count={zero_cnt}, null_count={null_cnt}, candidate_placeholder_value={repr(val)} (count={count})

Question: Can {repr(val)} be a biologically/domain valid value for this variable? Should {repr(val)} be treated as a missing placeholder?

Respond ONLY with structured JSON matching the requested schema."""

    last_exc = None
    for attempt in range(1, 4):
        try:
            decision = complete_json(prompt, PlaceholderDecision, temperature=0.1)
            decision.source = "language_model"
            return decision
        except Exception as exc:
            last_exc = exc
            logger.warning("Placeholder validation attempt %d failed for column '%s' (%s)", attempt, column, exc)
            if attempt < 3:
                time.sleep(2 ** attempt)

    logger.warning("Placeholder validation failed after 3 attempts for column '%s' (%s), using domain fallback.", column, last_exc)
    col_lower = column.lower()
    val_str = str(val).lower()

    # Domain fallback for common healthcare & sentinel placeholders
    if val == 0 or val_str == "0":
        if any(k in col_lower for k in ["bmi", "glucose", "bloodpressure", "bp", "insulin", "skinthickness", "age", "weight", "height", "cholesterol"]):
            return PlaceholderDecision(
                column=column,
                placeholder=True,
                placeholder_value=val,
                confidence=0.99,
                reason=f"{column} cannot be zero in biological adults or subjects; zero represents missing data.",
                action="replace_with_nan",
                source="heuristic_fallback",
            )
        elif any(k in col_lower for k in ["pregnanc", "child", "visit", "default", "count", "num", "idx", "id"]):
            return PlaceholderDecision(
                column=column,
                placeholder=False,
                placeholder_value=val,
                confidence=0.98,
                reason=f"Zero is a legitimate count or identifier for {column}.",
                action="keep",
                source="heuristic_fallback",
            )

    if val in [-999, 999, -99, -1] or val_str in ["unknown", "n/a", "na", "null", "none", "?"] or val_str == "":
        return PlaceholderDecision(
            column=column,
            placeholder=True,
            placeholder_value=val,
            confidence=0.95,
            reason=f"'{val}' is a standard sentinel value indicating missing or unknown data.",
            action="replace_with_nan",
            source="heuristic_fallback",
        )

    return PlaceholderDecision(
        column=column,
        placeholder=False,
        placeholder_value=val,
        confidence=0.85,
        reason=f"No strong domain evidence that '{val}' is a placeholder in '{column}'; retaining original value.",
        action="keep",
        source="heuristic_fallback",
    )
