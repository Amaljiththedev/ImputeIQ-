"""Placeholder detection and the conversion of placeholders to NaN.

These cover the cleaning stage: deciding which present-but-meaningless values
represent missing data, and applying that decision to the data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core import validation_service as vs


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """Force the heuristic fallback and remove the retry backoff.

    The semantic check calls Gemini first. Tests must not depend on a network
    service, and the real code sleeps 2s then 4s between its three attempts,
    so both are stubbed out here.
    """
    def _boom(*_a, **_k):
        raise RuntimeError("offline in tests")

    monkeypatch.setattr(vs, "_get_genai_client", _boom)
    monkeypatch.setattr(vs.time, "sleep", lambda *_: None)


@pytest.mark.parametrize(
    "column,value,expected_action",
    [
        # Zero is impossible for these measurements, so it encodes missingness.
        ("bmi", 0, "replace_with_nan"),
        ("glucose", 0, "replace_with_nan"),
        ("systolic_bp", 0, "replace_with_nan"),
        ("cholesterol", 0, "replace_with_nan"),
        # Zero is a legitimate count here and must survive cleaning.
        ("prior_pregnancies", 0, "keep"),
        ("visit_count", 0, "keep"),
        # Conventional sentinels regardless of column.
        ("anything", -999, "replace_with_nan"),
        ("anything", "unknown", "replace_with_nan"),
        ("anything", "n/a", "replace_with_nan"),
        ("anything", "", "replace_with_nan"),
    ],
)
def test_placeholder_decisions(column, value, expected_action):
    decision = vs._evaluate_placeholder_with_gemini(
        column=column, val=value, count=10, dtype_str="float64",
        min_val=0.0, max_val=50.0, zero_cnt=10, null_cnt=0,
    )
    assert decision.action == expected_action
    assert decision.source == "heuristic_fallback"
    assert decision.reason


def test_zero_in_bmi_and_pregnancies_are_treated_differently():
    """The distinction the semantic layer exists to make."""
    bmi = vs._evaluate_placeholder_with_gemini("bmi", 0, 5, "float64", 0.0, 50.0, 5, 0)
    preg = vs._evaluate_placeholder_with_gemini("prior_pregnancies", 0, 5, "int64", 0.0, 9.0, 5, 0)
    assert bmi.action == "replace_with_nan"
    assert preg.action == "keep"


def _apply_replacements(df: pd.DataFrame, replacements: list[tuple[str, object]]) -> pd.DataFrame:
    """Mirror of the conversion in routes.apply_dataset_validation_and_diagnose."""
    out = df.copy()
    for col, val in replacements:
        if col not in out.columns:
            continue
        if isinstance(val, str):
            target = val.strip().lower()
            out[col] = out[col].apply(
                lambda x: np.nan if isinstance(x, str) and x.strip().lower() == target else x
            )
        else:
            out[col] = out[col].replace(val, np.nan)
    return out


def test_string_placeholder_replacement_is_case_insensitive():
    """Regression test.

    Detection lowercases before matching and therefore reports "unknown", but
    the replacement used to be case-sensitive, so the "Unknown" actually present
    in the data was never converted. The placeholders survived cleaning, and
    because the column then contained no NaN it was dropped from diagnosis
    entirely.
    """
    df = pd.DataFrame({"region": ["North", "Unknown", "South", "UNKNOWN", " unknown "]})
    out = _apply_replacements(df, [("region", "unknown")])
    assert int(out["region"].isna().sum()) == 3
    assert set(out["region"].dropna()) == {"North", "South"}


def test_numeric_sentinel_replacement():
    df = pd.DataFrame({"cholesterol": [5.1, -999.0, 4.2, -999.0]})
    out = _apply_replacements(df, [("cholesterol", -999)])
    assert int(out["cholesterol"].isna().sum()) == 2


def test_empty_and_whitespace_strings_are_converted():
    df = pd.DataFrame({"notes": ["review", "", "   ", "follow-up"]})
    out = _apply_replacements(df, [("notes", "")])
    assert int(out["notes"].isna().sum()) == 2


def test_legitimate_zeros_are_untouched_by_conversion():
    df = pd.DataFrame({"prior_pregnancies": [0, 1, 0, 3]})
    out = _apply_replacements(df, [])
    assert int((out["prior_pregnancies"] == 0).sum()) == 2
    assert int(out["prior_pregnancies"].isna().sum()) == 0
