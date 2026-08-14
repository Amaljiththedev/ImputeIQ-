"""Canonicalising the action returned by the language model.

Regression tests. The model is asked for "replace_with_nan" or "keep" but does
not reliably return the exact literal; replies have included
"replace_with_null" and "fill_with_null". Every comparison downstream is
against the exact string, so an unrecognised synonym was read as "keep" and the
placeholder survived cleaning, while the model's own reason text said it should
have been removed. The failure was silent and produced wrong output data.
"""
from __future__ import annotations

import pytest

from app.core.validation_service import (
    ACTION_KEEP,
    ACTION_REPLACE,
    PlaceholderDecision,
    normalise_action,
)


def _decision(action: str, placeholder: bool = True) -> PlaceholderDecision:
    return PlaceholderDecision(
        column="bmi",
        placeholder=placeholder,
        placeholder_value=0,
        confidence=0.99,
        reason="BMI cannot be zero in a living person.",
        action=action,
    )


@pytest.mark.parametrize("wording", [
    "replace_with_nan",
    "replace_with_null",   # observed from the model
    "fill_with_null",      # observed from the model
    "fill_with_nan",
    "set_to_nan",
    "convert_to_null",
    "Replace With NaN",
    "replace-with-nan",
    "  REPLACE_WITH_NULL  ",
    "treat_as_missing",
])
def test_replacement_synonyms_all_canonicalise(wording):
    assert normalise_action(wording) == ACTION_REPLACE
    assert _decision(wording).action == ACTION_REPLACE


@pytest.mark.parametrize("wording", ["keep", "retain", "no_change", "leave_as_is", "KEEP", "ignore"])
def test_keep_synonyms_all_canonicalise(wording):
    assert normalise_action(wording) == ACTION_KEEP
    assert _decision(wording, placeholder=False).action == ACTION_KEEP


def test_unrecognised_wording_is_reported_as_unresolved():
    assert normalise_action("do_something_unexpected") is None
    assert normalise_action("") is None
    assert normalise_action(None) is None


def test_unrecognised_wording_defers_to_the_placeholder_flag():
    """The boolean is far less prone to paraphrase than the action string, so
    it decides when the wording cannot be understood."""
    assert _decision("banana", placeholder=True).action == ACTION_REPLACE
    assert _decision("banana", placeholder=False).action == ACTION_KEEP


def test_action_is_always_one_of_the_two_canonical_values():
    for wording in ["replace_with_null", "keep", "nonsense", "", "Convert"]:
        for flag in (True, False):
            assert _decision(wording, placeholder=flag).action in (ACTION_REPLACE, ACTION_KEEP)


def test_the_exact_bug_that_reached_production():
    """The model correctly reasoned that BMI cannot be zero, returned
    'replace_with_null', and the zeros were kept anyway."""
    d = PlaceholderDecision(
        column="bmi",
        placeholder=True,
        placeholder_value=0,
        confidence=0.99,
        reason="Body Mass Index cannot be 0 in a living human.",
        action="replace_with_null",
    )
    assert d.action == ACTION_REPLACE, "correct reasoning must not be discarded over wording"
