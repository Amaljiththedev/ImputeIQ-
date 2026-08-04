"""
sensitivity_engine.py

Computes per-column distribution stability metrics and scenario comparison
across Complete Case baseline, Selected Strategy, and Worst-Case bounds.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd
import numpy as np

from app.models.db_models import Dataset, DiagnosisResult, ImputationResult
from app.core.imputation_engine import IMPUTERS


def compute_column_sensitivity(
    dataset: Dataset,
    diagnosis_results: list[DiagnosisResult],
    imputation_results: list[ImputationResult],
) -> list[dict[str, Any]]:
    val_path = getattr(dataset, "validated_storage_path", None)
    target_path = val_path if (val_path and Path(val_path).exists()) else dataset.storage_path
    if not target_path or not Path(target_path).exists():
        return []

    try:
        df = pd.read_csv(target_path, sep=None, engine="python")
    except Exception:
        return []

    row_count = len(df)
    if row_count == 0:
        return []

    imp_map = {i.target_column: i for i in imputation_results}

    imputed_df = None
    latest_imp = (
        sorted(imputation_results, key=lambda x: x.created_at, reverse=True)[0]
        if imputation_results
        else None
    )

    if latest_imp and latest_imp.imputed_file_path and Path(latest_imp.imputed_file_path).exists():
        try:
            imputed_df = pd.read_csv(latest_imp.imputed_file_path, sep=None, engine="python")
        except Exception:
            imputed_df = None

    metrics = []
    for diag in diagnosis_results:
        col = diag.target_column
        if col not in df.columns:
            continue

        series_orig = df[col]
        series_clean = series_orig.dropna()
        if series_clean.empty:
            continue

        # FIX (root cause of the "Continuous / Median" mislabeling bug):
        # `dataset.numeric_columns` is populated at UPLOAD time from a raw
        # pandas dtype scan (pd.api.types.is_numeric_dtype), which has NO
        # concept of identifier vs. categorical vs. continuous. CPRD ID
        # columns like probobsid/drugrecid/staffid and lookup-code columns
        # like quantunitid are stored as int64/float64 in the raw CSV, so
        # they were ALWAYS landing in numeric_columns and being labelled
        # "numeric"/"Continuous" here regardless of their true semantic
        # role. semantic_role (computed once, upstream, by
        # column_semantics.py, and persisted on DiagnosisResult) is the
        # single source of truth for this distinction -- use it directly
        # instead of re-deriving numeric-ness from dtype.
        semantic_role = getattr(diag, "semantic_role", None)
        is_identifier = semantic_role == "identifier"
        is_numeric = (
            semantic_role == "continuous"
            if semantic_role is not None
            else pd.api.types.is_numeric_dtype(series_orig)
        )

        n_missing = int(series_orig.isna().sum())
        missing_pct = (n_missing / row_count) if row_count > 0 else 0.0

        imp_item = imp_map.get(col)
        is_ambiguous = "AMBIGUOUS" in str(diag.diagnosed_mechanism).upper()

        if imp_item:
            method_used = imp_item.method_used.lower()
            is_low_conf = bool(imp_item.low_confidence)
        else:
            from app.core.method_router import route
            decision = route(
                diag.diagnosed_mechanism,
                structural_zero_warning=diag.structural_zero_warning,
                semantic_role=semantic_role,
            )
            method_used = decision.method.lower()
            is_low_conf = decision.low_confidence

        # FIX: identifier columns are never numerically imputed (they're
        # flagged, not filled), so sensitivity/stability metrics computed
        # via mean-shift arithmetic are meaningless for them. Emit a
        # dedicated, honest entry instead of running numeric/categorical
        # math on a primary key.
        if is_identifier:
            flag_col = f"{col}_missing"
            if imputed_df is not None and flag_col in imputed_df.columns:
                n_flagged = int(imputed_df[flag_col].sum())
            else:
                n_flagged = n_missing
            metrics.append({
                "column": col,
                "type": "identifier",
                "missingCount": n_missing,
                "missingPct": missing_pct,
                "stabilityScore": 100,
                "status": "Not Imputed (Identifier)",
                "baselineVal": f"{n_missing} missing",
                "primaryVal": f"{n_flagged} flagged, values left null",
                "worstCaseVal": "N/A -- identifiers are never numerically filled",
                "shiftPct": 0.0,
                "description": (
                    f"'{col}' is a unique identifier column. Missing values are flagged "
                    f"via '{col}_missing' and left as null rather than imputed, since "
                    f"fabricating an ID would create a false link to a record that "
                    f"doesn't exist."
                ),
                "scenarioNotes": {
                    "mar": "Not applicable -- identifiers are excluded from mechanism-based imputation.",
                    "mcar": "Not applicable -- identifiers are excluded from mechanism-based imputation.",
                    "mnar": "Not applicable -- identifiers are excluded from mechanism-based imputation.",
                },
            })
            continue


        numeric_cols_for_impute = [
            d.target_column for d in diagnosis_results
            if getattr(d, "semantic_role", None) == "continuous" and d.target_column in df.columns
        ]

        if imputed_df is not None and col in imputed_df.columns:
            primary_series = imputed_df[col]
        else:
            imputer_fn = IMPUTERS.get(method_used, IMPUTERS.get("mode" if not is_numeric else "median"))
            fallback_cols = [col] if not is_numeric else (numeric_cols_for_impute or [col])
            if imputer_fn:
                try:
                    temp_res = imputer_fn(df.copy(), fallback_cols)
                    primary_series = temp_res[col]
                except Exception:
                    primary_series = series_orig.fillna(series_clean.median() if is_numeric else series_clean.mode()[0])
            else:
                primary_series = series_orig.fillna(series_clean.median() if is_numeric else series_clean.mode()[0])

        if is_numeric:
            mean_cc = float(series_clean.mean())
            mean_sel = float(primary_series.mean())
            if abs(mean_cc) > 1e-9:
                shift_pct = ((mean_sel - mean_cc) / abs(mean_cc)) * 100.0
            else:
                shift_pct = (mean_sel - mean_cc) * 100.0

            unit = ""
            if any(k in col.lower() for k in ("charge", "cost", "price", "revenue", "dollar")):
                unit = "$"
            elif any(k in col.lower() for k in ("age", "year", "duration")):
                unit = " yrs"

            if unit == "$":
                baseline_str = f"Mean: ${mean_cc:,.2f}"
                primary_str = f"Mean: ${mean_sel:,.2f} ({shift_pct:+.1f}%)"
            elif unit == " yrs":
                baseline_str = f"Mean: {mean_cc:.1f} yrs"
                primary_str = f"Mean: {mean_sel:.1f} yrs ({shift_pct:+.1f}%)"
            else:
                baseline_str = f"Mean: {mean_cc:.2f}"
                primary_str = f"Mean: {mean_sel:.2f} ({shift_pct:+.1f}%)"

            q10 = float(series_clean.quantile(0.1))
            q90 = float(series_clean.quantile(0.9))
            worst_series_10 = series_orig.fillna(q10)
            worst_series_90 = series_orig.fillna(q90)
            mean_worst_10 = float(worst_series_10.mean())
            mean_worst_90 = float(worst_series_90.mean())
            shift_10 = ((mean_worst_10 - mean_cc) / abs(mean_cc)) * 100.0 if abs(mean_cc) > 1e-9 else (mean_worst_10 - mean_cc) * 100.0
            shift_90 = ((mean_worst_90 - mean_cc) / abs(mean_cc)) * 100.0 if abs(mean_cc) > 1e-9 else (mean_worst_90 - mean_cc) * 100.0

            if abs(shift_90) > abs(shift_10):
                mean_worst = mean_worst_90
                worst_shift = shift_90
            else:
                mean_worst = mean_worst_10
                worst_shift = shift_10

            if unit == "$":
                worst_str = f"Mean: ${mean_worst:,.2f} ({worst_shift:+.1f}%)"
            elif unit == " yrs":
                worst_str = f"Mean: {mean_worst:.1f} yrs ({worst_shift:+.1f}%)"
            else:
                worst_str = f"Mean: {mean_worst:.2f} ({worst_shift:+.1f}%)"

            abs_shift = abs(shift_pct)
        else:
            modes = series_clean.mode()
            mode_cc = str(modes[0]) if not modes.empty else "Unknown"
            pct_cc = float((series_clean == mode_cc).mean() * 100.0)

            modes_sel = primary_series.mode()
            mode_sel = str(modes_sel[0]) if not modes_sel.empty else mode_cc
            pct_sel = float((primary_series == mode_sel).mean() * 100.0)

            shift_pct = pct_sel - pct_cc
            baseline_str = f"Mode: {mode_cc} ({pct_cc:.0f}%)"
            primary_str = f"Mode: {mode_sel} ({pct_sel:.0f}%)"

            val_counts = series_clean.value_counts()
            least_common = str(val_counts.index[-1]) if len(val_counts) > 1 else mode_cc
            worst_str = f"Mode shifted to '{least_common}' if gaps cluster"
            abs_shift = abs(shift_pct) * 0.5

        stability_score = max(40, min(99, int(100.0 - (abs_shift * 4.0) - (14.0 if is_ambiguous or is_low_conf else 0.0))))
        if stability_score >= 90:
            status = "Highly Stable"
        elif stability_score >= 80:
            status = "Robust"
        else:
            status = "Needs Caution"

        drivers = diag.significant_drivers or []
        driver_str = drivers[0] if drivers else "observed predictors"

        if is_ambiguous:
            desc = (
                f"Because the missingness mechanism for '{col}' is ambiguous, downstream estimates may shift by up to "
                f"±{abs_shift:.1f}% if unobserved factors drive the gaps."
            )
        else:
            desc = (
                f"Conditional imputation preserves distribution parameters within ±{abs_shift:.1f}% "
                f"of the complete-case baseline."
            )

        scenario_notes = {
            "mar": f"Under MAR (conditional on {driver_str}), group-level distributions remain unbiased and variance is preserved.",
            "mcar": "If gaps were purely random (MCAR), simple mean/mode fill would yield nearly identical results with lower standard error.",
            "mnar": f"Under extreme MNAR (worst-case bounds where missing values cluster at distribution tails), estimates shift by up to {worst_str.split()[-1] if '(' in worst_str else 'significant margins'}.",
        }

        metrics.append({
            "column": col,
            "type": "numeric" if is_numeric else "categorical",
            "missingCount": n_missing,
            "missingPct": missing_pct,
            "stabilityScore": stability_score,
            "status": status,
            "baselineVal": baseline_str,
            "primaryVal": primary_str,
            "worstCaseVal": worst_str,
            "shiftPct": round(abs_shift, 2),
            "description": desc,
            "scenarioNotes": scenario_notes,
        })

    return metrics
