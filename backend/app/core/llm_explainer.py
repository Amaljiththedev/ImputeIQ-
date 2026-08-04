"""
app/core/llm_explainer.py

Wraps the Gemini API to generate a plain-language explanation of a
dataset's diagnosis + imputation results, with:

1. Schema-enforced output (Gemini's response_schema, backed by the
   Pydantic models in explanation_schema.py) -- eliminates most
   malformed-JSON failures at the source.
2. Retry with fixed backoff (via tenacity) for transient failures
   (network errors, rate limits, 5xx) and for responses that fail Pydantic
   validation even after schema enforcement.

Note: generate_explanation() raises if Gemini fails after all retries, so
callers can decide how to handle it. _generate_fallback_explanation()
provides a deterministic, template-based explanation built purely from the
diagnosis/imputation results already computed locally -- used by the job
runners so a Gemini outage degrades the explanation text rather than
failing the whole pipeline. Results carry generated_by="template_fallback"
so the UI never presents template text as real model output.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from google import genai
from google.genai import types
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.core.explanation_schema import DatasetExplanation, MechanismExplanation

logger = logging.getLogger(__name__)

# Pinned to an explicit model version (not *-latest) so dissertation results
# stay reproducible. Override with the GEMINI_MODEL env var if this model is
# ever retired or sustained-unavailable.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
# MAX_RETRY_ATTEMPTS=1 meant stop_after_attempt(1) never actually retried --
# restored to a small number so transient failures (network blips, brief
# 5xx) get a genuine second/third chance before falling back. This does
# NOT protect against sustained 429 rate-limit exhaustion (see fallback
# below) -- no retry count can wait out a free-tier daily quota reset.
MAX_RETRY_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 1


class LLMGenerationError(Exception):
    """Raised when a Gemini call or its validation fails.
    Caught by the retry decorator; if retries are exhausted, the
    exception is propagated to the caller."""


@dataclass
class ExplanationResult:
    explanation: DatasetExplanation
    attempts: int
    generated_by: str = "gemini"  # "gemini" | "template_fallback" -- lets
    # the frontend show an honest "Generated automatically" badge instead
    # of presenting fallback text as if it were real Gemini output.


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your environment/.env before "
            "calling the LLM explainer."
        )
    return genai.Client(api_key=api_key)


def _build_prompt(column_reports: list[dict]) -> str:
    """Builds the user-facing prompt from structured diagnosis/imputation
    data. Deliberately data-only (no example JSON output pasted in, since
    duplicating the schema in the prompt is documented to reduce Gemini's
    structured-output quality)."""
    lines = [
        "You are an expert statistical consultant explaining missing-data diagnosis and imputation results to a domain analyst.",
        "Your goal is to maximize analytical depth, provide crystal-clear intuitive explanations, and offer concrete domain guidance without unnecessary jargon.",
        "",
        "For each column below, generate an exact structured explanation following the schema.",
        "Adhere to these high analytical standards across all fields:",
        "1. overall_summary: Write an authoritative, comprehensive executive synthesis of the dataset's missingness profile. Detail what dominant patterns emerged across variables (MCAR, MAR, or MNAR), evaluate the overall systemic quality of the data, and explain how the selected imputation strategies preserve variance, covariance, and downstream model accuracy.",
        "2. target_column: Must match the exact target column name from the report.",
        "3. plain_language_summary: Accurately summarize the diagnosed missing data mechanism (MCAR, MAR, or MNAR), the exact number/proportion of missing values, and the specific statistical evidence (e.g. Little's MCAR test, correlation p-values) driving this diagnosis.",
        "4. what_this_means_for_the_data: Explain the practical domain consequences of these gaps. Specifically note whether dropping rows would introduce bias, explain relationship dynamics with significant driver columns if identified, and outline potential risks if left untreated.",
        "5. imputation_explanation: Provide an illuminating technical explanation of WHY the chosen algorithm (e.g. Random Forest, PyAmpute/Ampute, Predictive Mean Matching, Median/Mode) was selected. Explain how this specific strategy handles the underlying mechanism while preserving distributional properties.",
        "6. confidence_note: Carefully evaluate confidence based on sample size, missingness proportion, and the 'low_confidence' flag. State clearly what factors strengthen or limit confidence in the diagnosis and imputation.",
        "7. recommended_action: Give a precise, actionable recommendation for next steps (e.g. inspecting outlier cases, performing sensitivity testing with alternative algorithms, or verifying assumptions with subject-matter experts).",
        "",
        "Column diagnosis and imputation reports:",
    ]
    for report in column_reports:
        lines.append(f"--- Column: {report['target_column']} ---")
        lines.append(f"  Diagnosed Mechanism: {report['diagnosed_mechanism']}")
        lines.append(f"  Statistical Diagnosis Detail: {report['diagnosis_detail']}")
        lines.append(f"  Missing Value Count: {report['n_missing']}")
        lines.append(f"  Imputation Method Applied: {report.get('method_used', 'N/A')}")
        lines.append(f"  Low Confidence Flag: {report.get('low_confidence', 'False')}")
        lines.append(f"  Algorithmic Routing Rationale: {report.get('rationale', 'N/A')}")
        lines.append("")
    return "\n".join(lines)


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_fixed(RETRY_WAIT_SECONDS),
    retry=retry_if_exception_type(LLMGenerationError),
)
def _call_gemini_with_retry(prompt: str) -> DatasetExplanation:
    """Single attempt wrapped in tenacity's retry decorator. Any failure
    (network, malformed response, schema validation failure) is raised as
    LLMGenerationError so tenacity retries it; after MAX_RETRY_ATTEMPTS the
    original exception is re-raised (reraise=True) for the caller to handle.
    """
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DatasetExplanation,
                temperature=0.2,  # low temperature: factual/explanatory task, not creative
            ),
        )
    except Exception as exc:  # network errors, rate limits, API errors, etc.
        logger.warning("Gemini API call failed: %s", exc)
        raise LLMGenerationError(str(exc)) from exc

    if not response.text:
        raise LLMGenerationError("Gemini returned an empty response.")

    try:
        explanation = DatasetExplanation.model_validate_json(response.text)
    except ValidationError as exc:
        logger.warning("Gemini response failed schema validation: %s", exc)
        raise LLMGenerationError(f"Schema validation failed: {exc}") from exc

    return explanation


def generate_explanation(column_reports: list[dict]) -> ExplanationResult:
    """Main entry point. Uses Gemini AI model with retries. If Gemini hits
    high-demand rate limits (503) or network issues, the exception is propagated.
    """
    if not column_reports:
        return ExplanationResult(
            explanation=DatasetExplanation(
                overall_summary="No columns had missing data.", columns=[]
            ),
            attempts=0,
            generated_by="gemini",
        )

    prompt = _build_prompt(column_reports)
    explanation = _call_gemini_with_retry(prompt)
    return ExplanationResult(
        explanation=explanation, attempts=MAX_RETRY_ATTEMPTS, generated_by="gemini"
    )


def _generate_fallback_explanation(column_reports: list[dict]) -> ExplanationResult:
    """Deterministic explanation built from the diagnosis/imputation results
    already computed locally -- no network call. Used by the job runners when
    generate_explanation() fails (Gemini outage, quota exhaustion, sustained
    5xx) so the pipeline still completes with honest, if plainer, text.
    """
    if not column_reports:
        return ExplanationResult(
            explanation=DatasetExplanation(
                overall_summary="No columns had missing data.", columns=[]
            ),
            attempts=0,
            generated_by="template_fallback",
        )

    columns: list[MechanismExplanation] = []
    low_confidence_cols: list[str] = []

    for report in column_reports:
        col = report.get("target_column", "unknown")
        mechanism = report.get("diagnosed_mechanism", "Uncertain")
        n_missing = report.get("n_missing", 0)
        method = report.get("method_used", "standard method")
        is_low = bool(report.get("low_confidence"))
        if is_low:
            low_confidence_cols.append(col)

        columns.append(
            MechanismExplanation(
                target_column=col,
                plain_language_summary=(
                    f"'{col}' had {n_missing} missing value(s), diagnosed as {mechanism}."
                ),
                what_this_means_for_the_data=report.get(
                    "diagnosis_detail",
                    "No further diagnostic detail was recorded for this column.",
                ),
                imputation_explanation=(
                    f"Imputed using {method}. "
                    f"{report.get('rationale', '')}".strip()
                ),
                confidence_note=(
                    "Low confidence — treat these imputed values as provisional and "
                    "confirm against domain knowledge before relying on them."
                    if is_low
                    else "Standard confidence based on the diagnosed mechanism and sample properties."
                ),
                recommended_action=(
                    "Verify the imputed distribution against domain expectations and "
                    "review any remaining outliers."
                ),
            )
        )

    caveat = (
        f" {len(low_confidence_cols)} column(s) were flagged low-confidence "
        f"({', '.join(low_confidence_cols)}) and need manual review."
        if low_confidence_cols
        else ""
    )
    overall = (
        f"Analysed {len(column_reports)} column(s) containing missing data. "
        f"Each was diagnosed for its missingness mechanism and imputed with a "
        f"method matched to that mechanism and to the column's semantic role.{caveat} "
        "This summary was generated automatically from the pipeline's own results "
        "because the language model was unavailable."
    )

    return ExplanationResult(
        explanation=DatasetExplanation(overall_summary=overall, columns=columns),
        attempts=0,
        generated_by="template_fallback",
    )


def generate_clarification(
    target_column: str,
    question: str,
    mechanism: str,
    diag_detail: str,
    rec_method: str,
    rationale: str,
) -> str:
    """Answers a user's interactive question on the approval screen regarding
    why a specific imputation method was recommended or comparing alternative methods.
    """
    prompt = (
        f"You are an expert statistical consultant assisting a domain analyst on the imputation approval screen.\n"
        f"The analyst has asked a question about the recommended missing data handling for column '{target_column}'.\n\n"
        f"Context:\n"
        f"- Target Column: {target_column}\n"
        f"- Diagnosed Mechanism: {mechanism}\n"
        f"- Statistical Evidence: {diag_detail}\n"
        f"- Recommended Imputation Method: {rec_method}\n"
        f"- Recommendation Rationale: {rationale}\n\n"
        f"User Question: \"{question}\"\n\n"
        f"Please provide a clear, insightful, professional, and concise plain-language answer addressing their exact question. "
        f"Explain trade-offs clearly without unnecessary mathematical notation."
    )
    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
        ),
    )
    if not response.text:
        raise LLMGenerationError("Gemini returned an empty response.")
    return response.text.strip()
