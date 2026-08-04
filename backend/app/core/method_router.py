"""
method_router.py

Routes a diagnosed missingness mechanism (from diagnose_mechanism.py) AND a
column's semantic role (from column_semantics.py) to an imputation method
(from imputation_engine.py), based on theoretical appropriateness rather
than textbook assumptions.

Routing precedence (checked in this order):
1. IDENTIFIER role       -> always "flag_only" (never impute a fabricated ID)
2. CATEGORICAL role      -> always "mode" (never median/mean on a lookup code)
3. Structural zero flag  -> "zero" (count column, only applies to CONTINUOUS)
4. CONTINUOUS / unknown  -> evidence-based MCAR/MAR/MNAR routing table

Semantic role is checked BEFORE the structural-zero and mechanism checks,
since role describes *what kind of value* a column holds, while mechanism
only describes *why* values are missing -- an identifier or category code
must never be routed to zero/median/mean regardless of its missingness
mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from app.core.imputation_engine import IMPUTERS

ROUTING_TABLE = {
    "MCAR": "mice",
    "MAR": "median",
    "MNAR": "median",
}

LOW_CONFIDENCE_MECHANISMS = {"MNAR"}

CONTINUOUS_RATIONALE = {
    "MCAR": "MICE is selected to robustly preserve multivariate distributions and variance under missing completely at random conditions.",
    "MAR": "Median is selected as a robust central tendency estimator; empirical tests generally show it performs comparably to MICE for MAR without the computational overhead.",
    "MNAR": "Median is applied as a baseline estimate, but no standard method is theoretically valid under MNAR -- flagged for manual review rather than trusted at face value.",
}


@dataclass
class RoutingDecision:
    mechanism: str
    method: str
    low_confidence: bool
    rationale: str
    semantic_role: str | None = None


def _normalize_role(semantic_role) -> str:
    if semantic_role is None:
        return ""
    if hasattr(semantic_role, "value"):
        return str(semantic_role.value).lower()
    return str(semantic_role).lower()


def _normalize_mechanism(diagnosed_mechanism: str) -> str:
    label = (diagnosed_mechanism or "").upper()
    if "AMBIGUOUS" in label:
        return "MNAR"
    if "MAR" in label and "MCAR" not in label:
        return "MAR"
    if "MCAR" in label:
        return "MCAR"
    if "MNAR" in label:
        return "MNAR"
    return "Uncertain"


def route(
    diagnosed_mechanism: str,
    structural_zero_warning: dict | None = None,
    user_override: bool = False,
    semantic_role: str | None = None,
) -> RoutingDecision:
    """
    IMPORTANT: the returned `method` is ALWAYS a valid key in IMPUTERS.
    This is asserted via _validate() so a typo fails loudly here instead
    of crashing with an opaque KeyError deep in the imputation step.
    """
    role_str = _normalize_role(semantic_role)
    label = (diagnosed_mechanism or "").upper()

    if role_str == "identifier":
        decision = RoutingDecision(
            mechanism="Identifier (key/ID)",
            method="flag_only",
            low_confidence=False,
            rationale=(
                "Column is a unique identifier or key (e.g. patid, staffid, "
                "probobsid, drugrecid). Imputing a statistical value here "
                "would fabricate a nonexistent patient/staff/observation/"
                "drug record link. Value is left missing and flagged via a "
                "'<col>_missing' indicator column instead."
            ),
            semantic_role=role_str,
        )
        return _validate(decision)

    if role_str == "categorical":
        decision = RoutingDecision(
            mechanism=diagnosed_mechanism or "Categorical",
            method="mode",
            low_confidence=("AMBIGUOUS" in label or "MNAR" in label),
            rationale=(
                "Column is a discrete/lookup-coded category (e.g. CPRD "
                "Lookup *.txt mapping such as quantunitid, medcodeid, "
                "patienttypeid). Mode (most frequent category) is used "
                "instead of median/mean/zero, since these codes are not on "
                "a continuous numeric scale and cannot be meaningfully "
                "averaged."
            ),
            semantic_role=role_str,
        )
        return _validate(decision)

    if structural_zero_warning or "STRUCTURAL" in label:
        decision = RoutingDecision(
            mechanism="Structural (event count)",
            method="zero",
            low_confidence=True,
            rationale=(
                "Missing values in this count column plausibly represent "
                "zero occurrences, not unknown values. Confirm with domain "
                "knowledge before accepting."
            ),
            semantic_role=role_str or "continuous",
        )
        return _validate(decision)

    mechanism = _normalize_mechanism(diagnosed_mechanism)

    if mechanism == "Uncertain":
        decision = RoutingDecision(
            mechanism=mechanism,
            method="median",
            low_confidence=True,
            rationale=f"Cautious default applied for diagnosed mechanism: {diagnosed_mechanism}.",
            semantic_role=role_str or "continuous",
        )
        return _validate(decision)

    method = ROUTING_TABLE[mechanism]
    low_confidence = mechanism in LOW_CONFIDENCE_MECHANISMS
    rationale = CONTINUOUS_RATIONALE[mechanism]

    decision = RoutingDecision(
        mechanism=mechanism,
        method=method,
        low_confidence=low_confidence,
        rationale=rationale,
        semantic_role=role_str or "continuous",
    )
    return _validate(decision)


def _validate(decision: RoutingDecision) -> RoutingDecision:
    if decision.method not in IMPUTERS:
        raise ValueError(
            f"route() produced method '{decision.method}' which is not a "
            f"registered imputer. Valid methods: {sorted(IMPUTERS.keys())}"
        )
    return decision


def apply_routed_imputation(
    df: pd.DataFrame,
    target_col: str,
    numeric_cols: list[str],
    diagnosed_mechanism: str,
    structural_zero_warning: dict | None = None,
    user_override: bool = False,
    semantic_role: str | None = None,
):
    """
    Column selection: "mode" and "flag_only" always operate on ONLY the
    target column. "mice"/"median"/"mean"/"knn"/"regression" operate on
    the full numeric_cols list, since those can use other numeric columns
    as predictors/context.
    """
    decision = route(
        diagnosed_mechanism,
        structural_zero_warning=structural_zero_warning,
        user_override=user_override,
        semantic_role=semantic_role,
    )
    imputer_fn = IMPUTERS[decision.method]

    single_column_methods = {"mode", "flag_only"}
    cols_to_impute = [target_col] if decision.method in single_column_methods else numeric_cols

    imputed_df = imputer_fn(df, cols_to_impute)
    return imputed_df, decision