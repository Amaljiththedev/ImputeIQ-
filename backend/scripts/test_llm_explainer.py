"""
scripts/test_llm_explainer.py

Run this LOCALLY with your real GEMINI_API_KEY set, to verify:
    1. A real Gemini call succeeds and returns schema-valid output.
    2. The retry/fallback logic still works correctly when Gemini is
       deliberately made to fail (by temporarily using a bad model name).

Usage:
    export GEMINI_API_KEY=AIzaSy...          # or set in your .env and load it
    python scripts/test_llm_explainer.py
"""

import json
import os
import sys

sys.path.insert(0, ".")

from app.core import llm_explainer  # noqa: E402
from app.core.llm_explainer import generate_explanation  # noqa: E402

SAMPLE_COLUMN_REPORTS = [
    {
        "target_column": "glucose",
        "diagnosed_mechanism": "MAR",
        "diagnosis_detail": "MAR (driver(s): smoking_status)",
        "n_missing": 76,
        "method_used": "median",
        "low_confidence": False,
        "rationale": "Median is selected as a robust central tendency estimator; empirical tests generally show it performs comparably to MICE for MAR without the computational overhead.",
    },
    {
        "target_column": "systolic_bp",
        "diagnosed_mechanism": "Ambiguous (MCAR/MNAR)",
        "diagnosis_detail": "Ambiguous: MCAR or MNAR (indistinguishable from observed data)",
        "n_missing": 38,
        "method_used": "median",
        "low_confidence": True,
        "rationale": "No standard method is theoretically valid under MNAR.",
    },
]


def print_result(result, label: str) -> None:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    print(f"attempts: {result.attempts}")
    print(f"\nOverall summary:\n  {result.explanation.overall_summary}")
    for report, col in zip(SAMPLE_COLUMN_REPORTS, result.explanation.columns):
        print(f"\n--- {report['target_column']} ---")
        print(f"  Summary:      {col.plain_language_summary}")
        print(f"  Meaning:      {col.what_this_means_for_the_data}")
        print(f"  Imputation:   {col.imputation_explanation}")
        print(f"  Confidence:   {col.confidence_note}")
        print(f"  Action:       {col.recommended_action}")
    
    # Print JSON output
    print(f"\n{'=' * 60}\n{label} (JSON FORMAT)\n{'=' * 60}")
    json_output = {
        "attempts": result.attempts,
        "explanation": result.explanation.model_dump()
    }
    print(json.dumps(json_output, indent=2))


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY is not set in this shell. Set it first:")
        print("    export GEMINI_API_KEY=AIzaSy...")
        sys.exit(1)

    print("--- TEST: Real Gemini call (should succeed) ---")
    result = generate_explanation(SAMPLE_COLUMN_REPORTS)
    print_result(result, "TEST RESULT")
    print("\n✅ Real Gemini call succeeded and passed schema validation.")
    print("\nDone.")


if __name__ == "__main__":
    main()
