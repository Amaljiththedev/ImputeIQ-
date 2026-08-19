"""
app/core/llm_explainer.py

Generates a plain-language explanation of a dataset's diagnosis and
imputation results. The provider lives behind app/core/llm_client.py.

1. Replies are validated against the Pydantic models in
   explanation_schema.py. The provider cannot enforce a schema server-side,
   so the shape is requested in the prompt and checked locally.
2. Retry with exponential backoff (via tenacity) for transient failures
   (network errors, rate limits, 5xx) and for replies that fail validation.

Note: generate_explanation() raises if the model fails after all retries, so
callers can decide how to handle it. _generate_fallback_explanation()
provides a deterministic, template-based explanation built purely from the
diagnosis/imputation results already computed locally -- used by the job
runners so a provider outage degrades the explanation text rather than
failing the whole pipeline. Results carry generated_by="template_fallback"
so the UI never presents template text as real model output.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.explanation_schema import DatasetExplanation, MechanismExplanation
from app.core.llm_client import LLMUnavailable, complete_json, complete_text

logger = logging.getLogger(__name__)
# Raised from 3 to 7 with exponential backoff. A rate limit is the common
# failure and it clears on its own: a fixed one-second gap retried three times
# gives up after three seconds, which is far too soon. The waits below run
# 2, 4, 8, 16, 30, 30 seconds, so a transient 429 or 5xx has about ninety
# seconds to clear before the template is used. The fallback still exists for
# a genuinely exhausted quota or a missing key, because no retry count can
# wait out a daily limit, and hanging the pipeline forever would be worse
# than plainer text -- but it should now be rare rather than routine.
MAX_RETRY_ATTEMPTS = 7
RETRY_WAIT_MIN_SECONDS = 2
RETRY_WAIT_MAX_SECONDS = 30


class LLMGenerationError(Exception):
    """Raised when a model call or its validation fails.
    Caught by the retry decorator; if retries are exhausted, the
    exception is propagated to the caller."""


@dataclass
class ExplanationResult:
    explanation: DatasetExplanation
    attempts: int
    # "language_model" | "template_fallback" -- lets the frontend show an
    # honest badge instead of presenting template text as real model output.
    generated_by: str = "language_model"




def _build_prompt(column_reports: list[dict]) -> str:
    """Builds the user-facing prompt from structured diagnosis/imputation
    data. Data only: complete_json() appends the JSON schema itself, so
    restating the shape here would duplicate it."""
    lines = [
        "You are an expert statistical consultant explaining missing-data diagnosis and imputation results to a domain analyst.",
        "Your goal is to maximize analytical depth, provide crystal-clear intuitive explanations, and offer concrete domain guidance without unnecessary jargon.",
        "",
        "For each column below, generate an exact structured explanation following the schema.",
        "Adhere to these high analytical standards across all fields:",
        "1. overall_summary: Write an authoritative, comprehensive executive synthesis of the dataset's missingness profile. Detail what dominant patterns emerged across variables (MCAR, MAR, or MNAR), evaluate the overall systemic quality of the data, and explain how the selected imputation strategies preserve variance, covariance, and downstream model accuracy.",
        "2. target_column: Must match the exact target column name from the report.",
        "3. plain_language_summary: Accurately summarize the diagnosed missing data mechanism (MCAR, MAR, or MNAR), the number and proportion of missing values, and the specific statistical evidence (e.g. Little's MCAR test, correlation p-values) driving this diagnosis. Both figures are supplied for each column below -- quote them exactly. Never write a placeholder letter or symbol in place of a number.",
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
        # The prompt asks for the proportion, so it has to supply the proportion.
        # It previously gave only the count, and the model answered with the
        # placeholder letters W, X, Y and Z where the percentages should have
        # been -- it had no row total to divide by. Percentages are arithmetic,
        # not language, so they are computed here.
        row_count = report.get("row_count")
        if row_count:
            pct = 100.0 * float(report["n_missing"]) / float(row_count)
            lines.append(f"  Total Rows: {row_count}")
            lines.append(f"  Missing Percentage: {pct:.1f}% (use this figure verbatim)")
        lines.append(f"  Imputation Method Applied: {report.get('method_used', 'N/A')}")
        lines.append(f"  Low Confidence Flag: {report.get('low_confidence', 'False')}")
        lines.append(f"  Algorithmic Routing Rationale: {report.get('rationale', 'N/A')}")
        lines.append("")
    return "\n".join(lines)


# A number was asked for and a letter came back: "852 missing values (~W%)".
# Matches a lone capital standing where a figure belongs, before a percent
# sign or after an approximation mark. Deliberately narrow -- "N%" and "X%"
# are the shapes actually seen, and widening it would start eating legitimate
# prose.
_PLACEHOLDER_NUMBER = re.compile(r"(?:[≈~]\s*[A-Z]\b|\b[A-Z]\s*%)")


def _find_placeholder_numbers(explanation: DatasetExplanation) -> list[str]:
    """Return every field still carrying a placeholder where a number belongs."""
    offenders = []
    for col in explanation.columns:
        for field, text in col.model_dump().items():
            if isinstance(text, str) and _PLACEHOLDER_NUMBER.search(text):
                offenders.append(f"{col.target_column}.{field}")
    if isinstance(explanation.overall_summary, str) and _PLACEHOLDER_NUMBER.search(
        explanation.overall_summary
    ):
        offenders.append("overall_summary")
    return offenders


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN_SECONDS, max=RETRY_WAIT_MAX_SECONDS),
    retry=retry_if_exception_type(LLMGenerationError),
)
def _call_model_with_retry(prompt: str) -> DatasetExplanation:
    """Single attempt wrapped in tenacity's retry decorator. Any failure
    (network, malformed response, schema validation failure) is raised as
    LLMGenerationError so tenacity retries it; after MAX_RETRY_ATTEMPTS the
    original exception is re-raised (reraise=True) for the caller to handle.
    """
    try:
        # Low temperature: this is a factual, explanatory task, not a creative one.
        explanation = complete_json(prompt, DatasetExplanation, temperature=0.2)
    except LLMUnavailable as exc:
        logger.warning("Explanation model call failed: %s", exc)
        raise LLMGenerationError(str(exc)) from exc

    # Schema validation passes on "(~W%)" because it is a well-formed string.
    # Treat it as a failed generation instead: retry, and fall back to the
    # template if the model keeps doing it. A placeholder on screen is worse
    # than plainer wording, because it reads as a real figure at a glance.
    offenders = _find_placeholder_numbers(explanation)
    if offenders:
        logger.warning("Explanation contained placeholder numbers in: %s", ", ".join(offenders))
        raise LLMGenerationError(
            f"placeholder used where a number belongs: {', '.join(offenders)}"
        )

    return explanation


def generate_explanation(column_reports: list[dict]) -> ExplanationResult:
    """Main entry point. Calls the model with retries. If the provider is rate
    limited or unreachable, the exception is propagated so the caller can fall
    back to _generate_fallback_explanation().
    """
    if not column_reports:
        return ExplanationResult(
            explanation=DatasetExplanation(
                overall_summary="No columns had missing data.", columns=[]
            ),
            attempts=0,
            generated_by="language_model",
        )

    prompt = _build_prompt(column_reports)
    explanation = _call_model_with_retry(prompt)
    return ExplanationResult(
        explanation=explanation, attempts=MAX_RETRY_ATTEMPTS, generated_by="language_model"
    )


def _generate_fallback_explanation(column_reports: list[dict]) -> ExplanationResult:
    """Deterministic explanation built from the diagnosis/imputation results
    already computed locally -- no network call. Used by the job runners when
    generate_explanation() fails (provider outage, quota exhaustion, sustained
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
    try:
        return complete_text(prompt, temperature=0.3)
    except LLMUnavailable as exc:  # quota exhaustion, network, API errors
        logger.warning("Clarification unavailable (%s); using the recorded rationale.", exc)

    # Degrade to the reasoning the pipeline already recorded rather than
    # failing the request. An unanswered question is a worse outcome than a
    # plainer answer, and the underlying facts are available locally.
    return (
        f"The language model could not be reached, so here is the reasoning already "
        f"recorded for '{target_column}'.\n\n"
        f"Diagnosed mechanism: {mechanism}.\n"
        f"Statistical evidence: {diag_detail}\n"
        f"Recommended method: {rec_method}.\n"
        f"Why: {rationale}\n\n"
        f"Your question was: \"{question}\". Ask again shortly for a fuller answer."
    )
