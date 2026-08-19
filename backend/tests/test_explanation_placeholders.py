"""
Regression tests for placeholder numbers in generated explanations.

A CPRD run produced four summaries reading "852 missing values (~W%)", with
the literal letters W, X, Y and Z standing where percentages belonged. The
prompt asked for the missing proportion but supplied only the raw count, so
the model had no denominator to divide by. Schema validation passed, because
"(~W%)" is a perfectly well-formed string, and the placeholders rendered on
the Overview tab looking exactly like real figures.

Two defences, one test each: give the prompt the percentage, and refuse the
reply if a placeholder comes back anyway.
"""

from app.core.explanation_schema import DatasetExplanation, MechanismExplanation
from app.core.llm_explainer import _build_prompt, _find_placeholder_numbers


def _column(**overrides) -> MechanismExplanation:
    fields = {
        "target_column": "value",
        "plain_language_summary": "value had 852 missing values (42.6%).",
        "what_this_means_for_the_data": "Dropping rows would bias the mean.",
        "imputation_explanation": "PMM draws from observed donors.",
        "confidence_note": "Confidence is moderate.",
        "recommended_action": "Inspect the sensitivity bounds.",
    }
    fields.update(overrides)
    return MechanismExplanation(**fields)


def _report(**overrides) -> dict:
    report = {
        "target_column": "value",
        "diagnosed_mechanism": "MAR",
        "diagnosis_detail": "Associated with medcodeid.",
        "n_missing": 852,
        "row_count": 2000,
        "method_used": "PMM",
        "low_confidence": False,
        "rationale": "van Buuren Table 1.1.",
    }
    report.update(overrides)
    return report


class TestPromptSuppliesTheProportion:
    def test_percentage_is_computed_and_included(self):
        prompt = _build_prompt([_report()])
        # 852 / 2000 = 42.6%. The model should never have to derive this.
        assert "42.6%" in prompt
        assert "Total Rows: 2000" in prompt

    def test_prompt_forbids_placeholders(self):
        prompt = _build_prompt([_report()])
        assert "placeholder" in prompt.lower()

    def test_missing_row_count_omits_percentage_rather_than_guessing(self):
        # Older callers may not pass row_count. Better to say nothing than to
        # print a percentage derived from an assumed denominator.
        prompt = _build_prompt([_report(row_count=None)])
        assert "Missing Percentage" not in prompt
        assert "Missing Value Count: 852" in prompt

    def test_zero_row_count_does_not_divide_by_zero(self):
        prompt = _build_prompt([_report(row_count=0)])
        assert "Missing Percentage" not in prompt


class TestPlaceholderDetection:
    def test_clean_explanation_has_no_offenders(self):
        explanation = DatasetExplanation(
            overall_summary="Eight columns had gaps.", columns=[_column()]
        )
        assert _find_placeholder_numbers(explanation) == []

    def test_catches_the_exact_shape_that_shipped(self):
        explanation = DatasetExplanation(
            overall_summary="Eight columns had gaps.",
            columns=[
                _column(
                    plain_language_summary="value had 852 missing values (≈W%)."
                )
            ],
        )
        assert _find_placeholder_numbers(explanation) == ["value.plain_language_summary"]

    def test_catches_tilde_variant(self):
        explanation = DatasetExplanation(
            overall_summary="Summary.",
            columns=[_column(confidence_note="Roughly ~X of the rows.")],
        )
        assert _find_placeholder_numbers(explanation) == ["value.confidence_note"]

    def test_catches_bare_letter_before_percent(self):
        explanation = DatasetExplanation(
            overall_summary="Summary.",
            columns=[_column(what_this_means_for_the_data="About Y% are absent.")],
        )
        assert _find_placeholder_numbers(explanation) == [
            "value.what_this_means_for_the_data"
        ]

    def test_checks_the_overall_summary_too(self):
        explanation = DatasetExplanation(
            overall_summary="Around Z% of the dataset is incomplete.",
            columns=[_column()],
        )
        assert _find_placeholder_numbers(explanation) == ["overall_summary"]

    def test_reports_every_offending_field(self):
        explanation = DatasetExplanation(
            overall_summary="Around Z% incomplete.",
            columns=[
                _column(plain_language_summary="852 values (≈W%)."),
                _column(target_column="numrangelow", confidence_note="~Y of rows."),
            ],
        )
        assert set(_find_placeholder_numbers(explanation)) == {
            "value.plain_language_summary",
            "numrangelow.confidence_note",
            "overall_summary",
        }

    def test_does_not_flag_ordinary_prose(self):
        # Real percentages, capitalised mechanism names and units must survive.
        explanation = DatasetExplanation(
            overall_summary="MAR dominates; 42.6% of value is missing.",
            columns=[
                _column(
                    plain_language_summary="MCAR was rejected at p < 0.05.",
                    imputation_explanation="MICE and PMM both apply under MAR.",
                    confidence_note="Little's test gave 12.3%, well above 5%.",
                )
            ],
        )
        assert _find_placeholder_numbers(explanation) == []
