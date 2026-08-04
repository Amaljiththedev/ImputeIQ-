from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from app.core.diagnose_mechanism import diagnose
from app.core.method_router import route, apply_routed_imputation

# Method names that operate on ONLY the target column, never the full
# numeric_cols list -- must stay in sync with method_router.py's
# single_column_methods set. "mode" (categorical) and "flag_only"
# (identifier) both apply to one column at a time.
SINGLE_COLUMN_METHODS = {"mode", "flag_only"}


@dataclass
class ColumnDiagnosis:
    target_column: str
    diagnosed_mechanism: str
    diagnosis_detail: str
    littles_p_value: float | None
    littles_suggests_mcar: bool
    categorical_assoc_p_values: dict
    numeric_assoc_p_values: dict
    significant_drivers: list
    n_missing: int
    structural_zero_warning: dict = None
    semantic_role: str = None


@dataclass
class ColumnImputation:
    target_column: str
    routed_mechanism: str
    method_used: str
    low_confidence: bool
    rationale: str
    n_imputed: int
    semantic_role: str = None


def diagnose_all_columns(
    df: pd.DataFrame, numeric_cols: list[str], categorical_cols: list[str]
) -> list[ColumnDiagnosis]:
    """
    Diagnoses every column with missing values, regardless of whether it
    was pre-classified as numeric or categorical by the caller. Uses
    column_semantics.py to determine each column's true semantic role
    (identifier / categorical / continuous), and back-fills numeric_cols /
    categorical_cols for any missing column that wasn't already tracked.
    """
    from app.core.diagnose_mechanism import run_littles_test, detect_structural_zero_candidate
    from app.core.column_semantics import classify_dataset_semantics, SemanticRole

    results: list[ColumnDiagnosis] = []
    semantic_map = classify_dataset_semantics(df)
    missing_cols = [col for col in df.columns if int(df[col].isna().sum()) > 0]
    if not missing_cols:
        return results

    try:
        shared_littles_p = run_littles_test(df, numeric_cols)
    except Exception:
        shared_littles_p = 1.0

    for col in missing_cols:
        n_missing = int(df[col].isna().sum())
        role_info = semantic_map.get(col)
        s_role = role_info.role.value if role_info else "continuous"

        if s_role == SemanticRole.IDENTIFIER.value:
            results.append(
                ColumnDiagnosis(
                    target_column=col,
                    diagnosed_mechanism="Identifier (key/ID)",
                    diagnosis_detail=(
                        "Column is a unique identifier/key; missingness mechanism "
                        "diagnosis skipped since imputation is never statistically "
                        "performed on identifier columns regardless of mechanism."
                    ),
                    littles_p_value=None,
                    littles_suggests_mcar=False,
                    categorical_assoc_p_values={},
                    numeric_assoc_p_values={},
                    significant_drivers=[],
                    n_missing=n_missing,
                    structural_zero_warning=None,
                    semantic_role=s_role,
                )
            )
            continue

        if col not in numeric_cols and col not in categorical_cols:
            if s_role == "continuous":
                numeric_cols.append(col)
            elif s_role == "categorical":
                categorical_cols.append(col)

        littles_p, littles_mcar, cat_assoc, num_assoc, drivers, diagnosis_detail = diagnose(
            df, col, numeric_cols, categorical_cols, littles_p=shared_littles_p
        )

        sz_warn = detect_structural_zero_candidate(df, col)

        if sz_warn:
            diag_mech = "Structural (event count)"
        elif diagnosis_detail.startswith("MAR"):
            diag_mech = "MAR"
        elif diagnosis_detail.startswith("Ambiguous"):
            diag_mech = "Ambiguous (MCAR/MNAR)"
        elif diagnosis_detail.startswith("Likely MNAR"):
            diag_mech = "MNAR"
        else:
            diag_mech = diagnosis_detail

        results.append(
            ColumnDiagnosis(
                target_column=col,
                diagnosed_mechanism=diag_mech,
                diagnosis_detail=diagnosis_detail,
                littles_p_value=littles_p,
                littles_suggests_mcar=littles_mcar,
                categorical_assoc_p_values=cat_assoc,
                numeric_assoc_p_values=num_assoc,
                significant_drivers=drivers,
                n_missing=n_missing,
                structural_zero_warning=sz_warn,
                semantic_role=s_role,
            )
        )
    return results


def impute_all_columns(
    df: pd.DataFrame, numeric_cols: list[str], diagnoses: list[ColumnDiagnosis]
) -> tuple[pd.DataFrame, list[ColumnImputation]]:
    """
    Applies the routed imputation method for every diagnosed column.
    Column selection (single-column vs. full numeric_cols) is delegated to
    apply_routed_imputation() in method_router.py, which is the single
    source of truth for that logic.
    """
    imputed_df = df.copy()
    imputations: list[ColumnImputation] = []

    for diag in diagnoses:
        col = diag.target_column
        decision = route(
            diag.diagnosed_mechanism,
            structural_zero_warning=diag.structural_zero_warning,
            semantic_role=diag.semantic_role,
        )

        temp_df, _ = apply_routed_imputation(
            imputed_df,
            col,
            numeric_cols,
            diag.diagnosis_detail,
            structural_zero_warning=diag.structural_zero_warning,
            semantic_role=diag.semantic_role,
        )
        imputed_df[col] = temp_df[col]

        # flag_only produces a companion "<col>_missing" indicator column --
        # carry it over into the output if present.
        flag_col = f"{col}_missing"
        if flag_col in temp_df.columns:
            imputed_df[flag_col] = temp_df[flag_col]

        imputations.append(
            ColumnImputation(
                target_column=col,
                routed_mechanism=decision.mechanism,
                method_used=decision.method,
                low_confidence=decision.low_confidence,
                rationale=decision.rationale,
                n_imputed=diag.n_missing,
                semantic_role=diag.semantic_role,
            )
        )

    return imputed_df, imputations


def impute_all_columns_with_overrides(
    df: pd.DataFrame,
    numeric_cols: list[str],
    diagnoses: list[ColumnDiagnosis],
    method_overrides: dict[str, str],
) -> tuple[pd.DataFrame, list[ColumnImputation]]:
    """
    Same as impute_all_columns, but allows the caller (e.g. a user in the
    UI) to override the routed method for specific columns.

    FIX: column-selection now checks SINGLE_COLUMN_METHODS (which contains
    the REAL registered method names "mode" and "flag_only"), instead of
    the stale placeholder names ("drop_or_null", "null") that never
    existed in imputation_engine.IMPUTERS. The old check silently fell
    through to the `else` branch for flag_only, which meant an identifier
    column's override would incorrectly flag missingness on the full
    numeric_cols list instead of the target identifier column itself.
    """
    from app.core.imputation_engine import IMPUTERS

    imputed_df = df.copy()
    imputations: list[ColumnImputation] = []

    for diag in diagnoses:
        col = diag.target_column
        override_method = method_overrides.get(col)
        decision = route(
            diag.diagnosed_mechanism,
            structural_zero_warning=diag.structural_zero_warning,
            user_override=bool(override_method),
            semantic_role=diag.semantic_role,
        )

        if override_method:
            chosen_key = override_method.lower()
        else:
            chosen_key = decision.method.lower()

        if chosen_key not in IMPUTERS:
            chosen_key = decision.method.lower()

        imputer_fn = IMPUTERS[chosen_key]
        cols_to_impute = [col] if chosen_key in SINGLE_COLUMN_METHODS else numeric_cols
        temp_df = imputer_fn(imputed_df, cols_to_impute)
        imputed_df[col] = temp_df[col]

        flag_col = f"{col}_missing"
        if flag_col in temp_df.columns:
            imputed_df[flag_col] = temp_df[flag_col]

        display_method = override_method or decision.method
        if chosen_key != decision.method.lower():
            rationale = (
                f"User selected {display_method} override. Original "
                f"recommendation: {decision.method} ({decision.rationale})"
            )
        else:
            rationale = decision.rationale

        imputations.append(
            ColumnImputation(
                target_column=col,
                routed_mechanism=decision.mechanism,
                method_used=display_method,
                low_confidence=decision.low_confidence,
                rationale=rationale,
                n_imputed=diag.n_missing,
                semantic_role=diag.semantic_role,
            )
        )

    return imputed_df, imputations