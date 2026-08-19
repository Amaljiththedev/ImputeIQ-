"""
sensitivity_engine.py

Computes per-column distribution stability metrics and scenario comparison
across Complete Case baseline, Selected Strategy, and Worst-Case bounds.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import pandas as pd
import numpy as np

from app.models.db_models import Dataset, DiagnosisResult, ImputationResult
from app.core.imputation_engine import IMPUTERS

logger = logging.getLogger(__name__)


# Which methods are unbiased under which mechanism, from van Buuren (2018)
# Table 1.1. Listwise deletion, mean and median are unbiased only under MCAR;
# stochastic regression (chained equations, and predictive mean matching as its
# matching variant) is unbiased under MAR and therefore also under MCAR, which
# is a special case of it.
#
# This matters for the comparison below. Including a method that is invalid for
# the diagnosed mechanism inflates the apparent disagreement: the estimates
# differ because one of them is wrong by construction, not because the result is
# fragile. Validity is therefore recorded per strategy, and the headline spread
# is computed over the valid ones only.
METHOD_VALIDITY = {
    "complete_case": {"MCAR"},
    "mean": {"MCAR"},
    "median": {"MCAR"},
    "mice": {"MCAR", "MAR"},
    "pmm": {"MCAR", "MAR"},
    "regression": {"MCAR", "MAR"},
}


def _is_valid_under(method: str, mechanism: str | None) -> bool:
    """Whether a method is unbiased under the diagnosed mechanism.

    Under MNAR nothing is valid without an untestable assumption, so no method
    is marked valid and the comparison becomes purely descriptive.
    """
    from app.core.diagnose_mechanism import MechanismClass, classify_mechanism

    cls = classify_mechanism(mechanism)
    if cls is MechanismClass.MNAR:
        return False
    if cls in (MechanismClass.UNRESOLVED, MechanismClass.OTHER):
        # The mechanism is not established, or none was supplied. Validity
        # cannot be claimed either way, so MAR is assumed: it is the more
        # demanding of the two, and assuming MCAR would license methods that
        # fail if that assumption is wrong.
        cls = MechanismClass.MAR
    return cls.value in METHOD_VALIDITY.get(method, set())


def compare_imputation_strategies(
    df: pd.DataFrame,
    target_col: str,
    numeric_cols: list[str],
    methods: tuple[str, ...] = ("complete_case", "median", "mean", "pmm", "mice"),
    mechanism: str | None = None,
) -> list[dict[str, Any]]:
    """Estimate the same quantity under several imputation strategies.

    The per-column metrics elsewhere in this module describe what imputation did
    to a column's distribution. They do not answer the question that matters for
    a report: would the number I quote change if I had chosen differently?

    Here the same estimate -- the column mean -- is recomputed under each
    strategy, including complete-case analysis as the do-nothing baseline. If
    the estimate is stable across all of them, a conclusion resting on it does
    not depend on the imputation choice. If it moves, the choice is doing work
    and must be reported, which is what CONSORT item 21c asks for.
    """
    from app.core.imputation_engine import IMPUTERS

    observed = pd.to_numeric(df[target_col], errors="coerce")
    n_missing = int(observed.isna().sum())
    results: list[dict[str, Any]] = []

    for method in methods:
        try:
            if method == "complete_case":
                series = observed.dropna()
            else:
                fn = IMPUTERS.get(method)
                if fn is None:
                    continue
                cols = [c for c in numeric_cols if c in df.columns] or [target_col]
                filled = fn(df.copy(), cols)
                series = pd.to_numeric(filled[target_col], errors="coerce").dropna()

            if series.empty:
                continue
            results.append({
                "strategy": method,
                "estimate": round(float(series.mean()), 4),
                "sd": round(float(series.std(ddof=1)), 4) if len(series) > 1 else 0.0,
                "n": int(len(series)),
                "valid_under_mechanism": _is_valid_under(method, mechanism),
            })
        except Exception as exc:  # a strategy that cannot run is reported, not fatal
            logger.warning("Strategy %s unavailable for %s: %s", method, target_col, exc)

    if results:
        reference = abs(results[0]["estimate"]) or 1.0
        for r in results:
            r["shift_vs_complete_case_pct"] = round(
                (r["estimate"] - results[0]["estimate"]) / reference * 100.0, 2
            )

        # Headline spread over methods that are actually valid for this
        # mechanism. Including an invalid method would report disagreement that
        # is expected rather than informative.
        valid = [r["estimate"] for r in results if r.get("valid_under_mechanism")]
        allest = [r["estimate"] for r in results]
        spread_valid = (max(valid) - min(valid)) if len(valid) > 1 else 0.0

        results.append({
            "strategy": "__summary__",
            "n_missing": n_missing,
            "mechanism": mechanism,
            "valid_methods": [r["strategy"] for r in results if r.get("valid_under_mechanism")],
            "estimate_range": [round(min(valid), 4), round(max(valid), 4)] if valid else None,
            "estimate_range_all_methods": [round(min(allest), 4), round(max(allest), 4)],
            "spread": round(spread_valid, 4),
            "spread_pct_of_estimate": round(spread_valid / reference * 100.0, 2),
            "note": (
                "Spread is measured across methods that are unbiased under the diagnosed "
                "mechanism (van Buuren 2018, Table 1.1). Methods valid only under MCAR are "
                "shown for contrast but excluded from it."
                if valid else
                "No method is unbiased under this mechanism, so the comparison is descriptive only."
            ),
        })
    return results


def mnar_delta_sweep(
    df: pd.DataFrame,
    target_col: str,
    numeric_cols: list[str],
    deltas: tuple[float, ...] = (-1.0, -0.5, 0.0, 0.5, 1.0),
    method: str = "pmm",
) -> list[dict[str, Any]]:
    """Tipping-point analysis over assumed MNAR departures.

    MNAR cannot be tested for, so the only honest treatment is to assume a range
    of departures and report how far the estimate travels. Each missing value is
    imputed as usual and then shifted by delta standard deviations of the
    observed data. Delta zero is the MAR assumption the pipeline actually uses;
    the others ask what happens if the unrecorded values were systematically
    higher or lower than the model supposes.

    A conclusion that survives the whole sweep does not depend on the MAR
    assumption. One that does not survive it should be reported with that
    caveat rather than as a single number.
    """
    from app.core.imputation_engine import IMPUTERS

    observed = pd.to_numeric(df[target_col], errors="coerce")
    obs_only = observed.dropna()
    if obs_only.empty or observed.isna().sum() == 0:
        return []

    sd = float(obs_only.std(ddof=1)) if len(obs_only) > 1 else 0.0
    baseline = float(obs_only.mean())

    fn = IMPUTERS.get(method, IMPUTERS["median"])
    cols = [c for c in numeric_cols if c in df.columns] or [target_col]
    try:
        filled = pd.to_numeric(fn(df.copy(), cols)[target_col], errors="coerce")
    except Exception:
        filled = observed.fillna(obs_only.median())

    gaps = observed.isna()
    missing_fraction = float(gaps.mean())

    # The shift is applied only to the imputed cells, so its effect on the
    # overall mean is delta * sd * missing_fraction. A column that is 50%
    # missing therefore moves ten times as far as one that is 5% missing under
    # the same assumed departure. Reporting only the percentage movement would
    # conflate the strength of the assumption with the amount of missing data
    # and make columns incomparable, so both the fraction and the movement
    # expressed per unit of missingness are returned alongside it.
    out: list[dict[str, Any]] = []
    for delta in deltas:
        shifted = filled.copy()
        shifted[gaps] = shifted[gaps] + delta * sd
        est = float(shifted.mean())
        movement = est - baseline
        out.append({
            "delta_sd": delta,
            "estimate": round(est, 4),
            "shift_vs_observed_pct": round(movement / (abs(baseline) or 1.0) * 100.0, 2),
            # Movement expressed in standard deviations of the observed data,
            # which is comparable across columns of different scale.
            "shift_in_sd": round(movement / sd, 4) if sd > 0 else 0.0,
            "missing_fraction": round(missing_fraction, 4),
            # What the same assumed departure would do at 100% missingness,
            # isolating the strength of the assumption from how much is absent.
            "shift_per_unit_missing_pct": round(
                (movement / (abs(baseline) or 1.0) * 100.0) / missing_fraction, 2
            ) if missing_fraction > 0 else 0.0,
            "assumption": (
                "MAR, as routed" if delta == 0
                else f"missing values {'higher' if delta > 0 else 'lower'} by {abs(delta)} SD"
            ),
        })
    return out


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
        # Expressed as a true percentage (0-100). This previously stored the raw
        # fraction in a field named missingPct, so any consumer rendering it
        # directly understated missingness by a factor of 100.
        missing_pct = (n_missing / row_count * 100.0) if row_count > 0 else 0.0

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
                "missingPct": round(missing_pct, 2),
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

        # ------------------------------------------------------------------
        # Stability is measured against what single imputation actually damages.
        #
        # The previous implementation compared only the MEAN before and after.
        # Median (and mode) imputation barely moves a mean by construction, so
        # that comparison returned near-zero for every column and the score
        # collapsed to a constant. It reported "Robust" precisely where the
        # distribution was being distorted most.
        #
        # Filling n missing values with a single constant shrinks the spread.
        # Variance retention captures that directly, so it is the headline
        # figure here, with the standardised mean shift as a second axis.
        # ------------------------------------------------------------------
        if is_numeric:
            obs = pd.to_numeric(series_clean, errors="coerce").dropna().astype(float)
            imp = pd.to_numeric(primary_series, errors="coerce").dropna().astype(float)
            if obs.empty or imp.empty:
                continue

            mean_obs = float(obs.mean())
            mean_imp = float(imp.mean())
            sd_obs = float(obs.std(ddof=1)) if len(obs) > 1 else 0.0
            sd_imp = float(imp.std(ddof=1)) if len(imp) > 1 else 0.0

            shift_pct = ((mean_imp - mean_obs) / abs(mean_obs) * 100.0) if abs(mean_obs) > 1e-9 else 0.0
            abs_shift = abs(shift_pct)
            # Mean shift expressed in standard deviations, so it is comparable
            # across columns measured on different scales.
            std_shift = (abs(mean_imp - mean_obs) / sd_obs) if sd_obs > 1e-9 else 0.0
            var_retention = (sd_imp / sd_obs) if sd_obs > 1e-9 else 1.0
            sd_change_pct = (var_retention - 1.0) * 100.0

            baseline_str = f"Mean {mean_obs:,.2f} · SD {sd_obs:,.2f}"
            primary_str = (
                f"Mean {mean_imp:,.2f} ({shift_pct:+.2f}%) · SD {sd_imp:,.2f} ({sd_change_pct:+.1f}%)"
            )

            # Delta-adjusted MNAR bound. Rather than filling from the observed
            # 10th/90th percentile (which stays inside the observed support and
            # therefore cannot bound an MNAR departure), the missing values are
            # shifted by one standard deviation in each direction and the larger
            # resulting movement is reported. This is the tipping-point style
            # adjustment CONSORT item 21c expects for MNAR scenarios.
            if n_missing > 0 and sd_obs > 1e-9:
                filled_hi = series_orig.fillna(mean_obs + sd_obs)
                filled_lo = series_orig.fillna(mean_obs - sd_obs)
                mean_hi = float(pd.to_numeric(filled_hi, errors="coerce").mean())
                mean_lo = float(pd.to_numeric(filled_lo, errors="coerce").mean())
                shift_hi = ((mean_hi - mean_obs) / abs(mean_obs) * 100.0) if abs(mean_obs) > 1e-9 else 0.0
                shift_lo = ((mean_lo - mean_obs) / abs(mean_obs) * 100.0) if abs(mean_obs) > 1e-9 else 0.0
                if abs(shift_hi) >= abs(shift_lo):
                    worst_mean, worst_shift = mean_hi, shift_hi
                else:
                    worst_mean, worst_shift = mean_lo, shift_lo
                worst_str = f"Mean {worst_mean:,.2f} ({worst_shift:+.2f}%) at δ = ±1 SD"
            else:
                worst_shift = 0.0
                worst_str = "No missing values to bound"

            # Score is the weaker of two fidelities, so a column cannot look
            # healthy by doing well on one axis alone. Spread fidelity is
            # penalised for departure from the original SD in EITHER direction:
            # constant-fill far from the centre (zero-filling a count column,
            # say) inflates the SD rather than shrinking it, and clipping that
            # to 1.0 would report perfect stability alongside a large mean shift.
            var_fidelity = max(0.0, 1.0 - abs(1.0 - var_retention))
            mean_fidelity = max(0.0, 1.0 - min(1.0, std_shift))
            stability_score = int(round(min(var_fidelity, mean_fidelity) * 100))

            if var_fidelity >= 0.95 and std_shift < 0.10:
                status = "Highly Stable"
            elif var_fidelity >= 0.90 and std_shift < 0.25:
                status = "Robust"
            else:
                status = "Needs Caution"

            spread_word = "narrows" if var_retention < 1.0 else "widens"
            desc = (
                f"Imputing {n_missing:,} value(s) leaves {var_retention * 100:.1f}% of the original "
                f"standard deviation and moves the mean by {std_shift:.2f} SD ({shift_pct:+.2f}%). "
                f"Filling with a single constant {spread_word} the spread, so the resulting variance "
                f"misstates the true uncertainty."
            )
        else:
            # Categorical: compare the full category distribution, not just the
            # modal share. Total variation distance is bounded [0, 1] and moves
            # whenever any category's proportion changes.
            obs_props = series_clean.astype(str).value_counts(normalize=True)
            imp_props = primary_series.dropna().astype(str).value_counts(normalize=True)
            categories = set(obs_props.index) | set(imp_props.index)
            tvd = 0.5 * sum(
                abs(float(imp_props.get(c, 0.0)) - float(obs_props.get(c, 0.0))) for c in categories
            )

            mode_obs = str(obs_props.index[0]) if len(obs_props) else "Unknown"
            pct_obs = float(obs_props.iloc[0] * 100.0) if len(obs_props) else 0.0
            mode_imp = str(imp_props.index[0]) if len(imp_props) else mode_obs
            pct_imp = float(imp_props.iloc[0] * 100.0) if len(imp_props) else pct_obs

            shift_pct = pct_imp - pct_obs
            abs_shift = abs(shift_pct)

            baseline_str = f"Mode '{mode_obs}' ({pct_obs:.1f}%) · {len(obs_props)} categories"
            primary_str = f"Mode '{mode_imp}' ({pct_imp:.1f}%) · TVD {tvd:.3f}"

            rarest = str(obs_props.index[-1]) if len(obs_props) > 1 else mode_obs
            worst_share = (n_missing / row_count * 100.0) if row_count else 0.0
            worst_str = f"'{rarest}' +{worst_share:.1f}pp if all gaps were that category"
            worst_shift = worst_share

            stability_score = int(round(max(0.0, 1.0 - tvd) * 100))
            if tvd <= 0.02:
                status = "Highly Stable"
            elif tvd <= 0.05:
                status = "Robust"
            else:
                status = "Needs Caution"

            desc = (
                f"Filling {n_missing:,} gap(s) with the mode shifts the category distribution by a total "
                f"variation distance of {tvd:.3f}, raising the modal share from {pct_obs:.1f}% to "
                f"{pct_imp:.1f}%. Mode imputation always concentrates mass on the majority category."
            )

        if is_ambiguous or is_low_conf:
            desc += " The mechanism is uncertain, so this comparison bounds the arithmetic effect only, not the risk of bias."

        drivers = diag.significant_drivers or []
        driver_str = drivers[0] if drivers else "observed predictors"

        scenario_notes = {
            "mar": (
                f"Under MAR the missingness is explained by {driver_str}. Estimates are recoverable only if "
                f"the imputation conditions on that variable; an unconditional fill does not."
            ),
            "mcar": (
                "Under MCAR the observed cases are a random subsample, so complete-case estimates are already "
                "unbiased and imputation mainly recovers statistical power."
            ),
            "mnar": (
                f"Under MNAR, shifting the missing values by one standard deviation moves the mean by "
                f"{worst_shift:+.2f}%. MNAR cannot be confirmed from the observed data, so this is a "
                f"sensitivity bound rather than an estimate."
            ),
        }

        metrics.append({
            "column": col,
            "type": "numeric" if is_numeric else "categorical",
            "missingCount": n_missing,
            "missingPct": round(missing_pct, 2),
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
