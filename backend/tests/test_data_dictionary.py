"""User-supplied data dictionaries and stated column assumptions.

Placeholder decisions depend on what a column is taken to mean. Previously that
interpretation was inferred from the column name and never shown, so a wrong
reading of a misleading name silently changed the data. These cover the two
remedies: letting the user describe their own columns, and stating the
interpretation for approval before anything is applied.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from app.core import validation_service as vs
from app.core.validation_service import (
    infer_column_assumptions,
    parse_data_dictionary,
)


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("offline in tests")
    monkeypatch.setattr(vs, "complete_json", _boom)
    monkeypatch.setattr(vs.time, "sleep", lambda *_: None)


# --------------------------------------------------------------------------
# Parsing. Data dictionaries vary widely in shape, so parsing is permissive.
# --------------------------------------------------------------------------

def test_parses_json_object():
    got = parse_data_dictionary('{"bmi": "Body mass index in kg/m2", "yob": "Year of birth"}')
    assert got["bmi"] == "Body mass index in kg/m2"
    assert got["yob"] == "Year of birth"


def test_parses_json_list_of_records():
    content = json.dumps([
        {"column": "patid", "description": "Patient identifier"},
        {"name": "sbp", "meaning": "Systolic blood pressure, mmHg"},
    ])
    got = parse_data_dictionary(content)
    assert got["patid"] == "Patient identifier"
    assert got["sbp"] == "Systolic blood pressure, mmHg"


@pytest.mark.parametrize("line,col,desc", [
    ("bmi: Body mass index", "bmi", "Body mass index"),
    ("bmi = Body mass index", "bmi", "Body mass index"),
    ("bmi - Body mass index", "bmi", "Body mass index"),
    ("bmi,Body mass index", "bmi", "Body mass index"),
])
def test_parses_common_plain_text_separators(line, col, desc):
    assert parse_data_dictionary(line)[col] == desc


def test_ignores_blank_lines_and_comments():
    got = parse_data_dictionary("# my dictionary\n\nbmi: Body mass index\n\n")
    assert got == {"bmi": "Body mass index"}


def test_column_lookup_is_case_insensitive():
    assert "bmi" in parse_data_dictionary("BMI: Body mass index")


@pytest.mark.parametrize("content", [None, "", "   ", "\n\n"])
def test_empty_dictionary_is_no_dictionary(content):
    assert parse_data_dictionary(content) == {}


# --------------------------------------------------------------------------
# Assumptions
# --------------------------------------------------------------------------

@pytest.fixture
def frame():
    return pd.DataFrame({
        "bmi": [22.1, 27.4, 31.0, 0.0],
        "xq7": [1, 2, 3, 4],
        "grp": ["a", "b", "a", "b"],
    })


def test_user_description_is_used_and_needs_no_review(frame):
    a = {x.column: x for x in infer_column_assumptions(frame, {"bmi": "Body mass index, kg/m2"})}
    assert a["bmi"].source == "user_dictionary"
    assert a["bmi"].assumed_meaning == "Body mass index, kg/m2"
    assert a["bmi"].needs_review is False


def test_every_column_gets_an_assumption(frame):
    assert {a.column for a in infer_column_assumptions(frame, {})} == set(frame.columns)


def test_undescribed_columns_are_flagged_for_review(frame):
    """The inferred reading of a name is the guess that needs checking, so it
    must never be presented as settled."""
    for a in infer_column_assumptions(frame, {"bmi": "Body mass index"}):
        if a.column != "bmi":
            assert a.needs_review is True
            assert a.source in ("language_model", "unavailable")


def test_assumptions_are_honest_when_inference_is_unavailable(frame):
    """With the model unreachable the tool must say it does not know, rather
    than inventing a meaning."""
    for a in infer_column_assumptions(frame, {}):
        assert a.source == "unavailable"
        assert "Not established" in a.assumed_meaning


def test_assumptions_follow_column_order(frame):
    got = [a.column for a in infer_column_assumptions(frame, {"grp": "Group"})]
    assert got == list(frame.columns)


def test_a_misleading_name_can_be_corrected_by_the_user():
    """The case the supervisor raised: a name that reads as one thing and means
    another. The user's description must win."""
    df = pd.DataFrame({"weight": [0.2, 0.5, 0.3]})
    a = infer_column_assumptions(df, {"weight": "Survey sampling weight, 0-1, not body weight"})[0]
    assert a.source == "user_dictionary"
    assert "sampling weight" in a.assumed_meaning
    assert a.needs_review is False


def test_detection_method_is_stated_for_the_user():
    text = vs.DETECTION_METHOD_DESCRIPTION
    assert "language model" in text
    assert "misleading" in text
    assert "data dictionary" in text
