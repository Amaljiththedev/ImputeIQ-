"""Imputer behaviour and the sensitivity metric."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.imputation_engine import IMPUTERS, impute_flag, impute_median, impute_mode
from app.core.sensitivity_engine import compute_column_sensitivity


# --------------------------------------------------------------------------
# Imputers
# --------------------------------------------------------------------------

def test_imputation_never_alters_observed_values():
    """The core integrity property: gaps get filled, recorded data does not move."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"x": rng.normal(10, 2, 200), "y": rng.normal(5, 1, 200)})
    df.loc[rng.choice(200, 40, replace=False), "x"] = np.nan
    observed = df["x"].notna()

    for name, fn in IMPUTERS.items():
        cols = ["x"] if name in ("mode", "flag_only") else ["x", "y"]
        out = fn(df.copy(), cols)
        assert np.allclose(
            df.loc[observed, "x"], out.loc[observed, "x"], equal_nan=False
        ), f"{name} modified observed values"


def test_flag_only_leaves_values_missing_and_adds_an_indicator():
    df = pd.DataFrame({"patid": ["a", None, "c", None]})
    out = impute_flag(df, ["patid"])
    assert "patid_missing" in out.columns
    assert int(out["patid"].isna().sum()) == 2, "identifier values must not be fabricated"
    assert out["patid_missing"].tolist() == [False, True, False, True]


def test_median_fills_every_gap():
    df = pd.DataFrame({"x": [1.0, np.nan, 3.0, np.nan, 5.0]})
    out = impute_median(df, ["x"])
    assert int(out["x"].isna().sum()) == 0
    assert out.loc[1, "x"] == pytest.approx(3.0)


def test_mode_fills_categoricals_with_an_existing_category():
    df = pd.DataFrame({"g": ["a", "a", "b", None, None]})
    out = impute_mode(df, ["g"])
    assert int(out["g"].isna().sum()) == 0
    assert set(out["g"]) <= {"a", "b"}, "mode must not invent a category"


def test_single_imputation_shrinks_spread():
    """Documents the known cost of constant fill, which the sensitivity metric
    exists to surface."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.normal(0, 1, 500)})
    sd_before = df["x"].std()
    df.loc[rng.choice(500, 150, replace=False), "x"] = np.nan
    sd_after = impute_median(df.copy(), ["x"])["x"].std()
    assert sd_after < sd_before


# --------------------------------------------------------------------------
# Sensitivity metric
# --------------------------------------------------------------------------

class _Obj:
    """Minimal stand-in for the ORM rows the engine reads attributes from."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def sensitivity_inputs(tmp_path):
    rng = np.random.default_rng(2)
    n = 400
    df = pd.DataFrame({
        "bmi": rng.normal(27, 5, n).round(2),
        "age": rng.normal(50, 12, n).round(0),
    })
    df.loc[rng.choice(n, 120, replace=False), "bmi"] = np.nan
    path = tmp_path / "d.csv"
    df.to_csv(path, index=False)

    dataset = _Obj(id="d1", storage_path=str(path), validated_storage_path=None)
    diag = _Obj(target_column="bmi", diagnosed_mechanism="MAR", semantic_role="continuous",
                structural_zero_warning=None, significant_drivers=[], n_missing=120)
    return dataset, [diag], []


def test_missing_pct_is_a_percentage_not_a_fraction(sensitivity_inputs):
    """Regression test: the field is named missingPct but used to hold the raw
    fraction, understating missingness by a factor of 100."""
    dataset, diags, imps = sensitivity_inputs
    m = compute_column_sensitivity(dataset, diags, imps)[0]
    assert m["missingPct"] == pytest.approx(30.0, abs=0.5)


def test_metric_detects_variance_loss(sensitivity_inputs):
    """Regression test: scoring on mean shift alone returned a near-constant
    value, because median imputation barely moves a mean by construction."""
    dataset, diags, imps = sensitivity_inputs
    m = compute_column_sensitivity(dataset, diags, imps)[0]
    assert m["stabilityScore"] < 100
    assert "SD" in m["primaryVal"], "spread must be reported alongside the mean"


def test_identifier_columns_are_reported_as_not_imputed(tmp_path):
    # Two columns on purpose: the engine reads with sep=None, and pandas'
    # delimiter sniffing raises on a single-column file, which the engine
    # swallows and returns no metrics for.
    df = pd.DataFrame({
        "patid": ["a", None, "c", None, "e"],
        "age": [40, 51, 62, 33, 45],
    })
    path = tmp_path / "d.csv"
    df.to_csv(path, index=False)
    dataset = _Obj(id="d2", storage_path=str(path), validated_storage_path=None)
    diag = _Obj(target_column="patid", diagnosed_mechanism="Identifier (key/ID)",
                semantic_role="identifier", structural_zero_warning=None,
                significant_drivers=[], n_missing=2)

    m = compute_column_sensitivity(dataset, [diag], [])[0]
    assert m["status"] == "Not Imputed (Identifier)"
    assert m["type"] == "identifier"


def test_scores_differentiate_between_columns(tmp_path):
    """The old formula collapsed to a constant for every column; a column with
    far more missingness must not score the same as one with very little."""
    rng = np.random.default_rng(3)
    n = 400
    df = pd.DataFrame({
        "heavy": rng.normal(20, 6, n).round(2),
        "light": rng.normal(20, 6, n).round(2),
    })
    df.loc[rng.choice(n, 200, replace=False), "heavy"] = np.nan
    df.loc[rng.choice(n, 10, replace=False), "light"] = np.nan
    path = tmp_path / "d.csv"
    df.to_csv(path, index=False)

    dataset = _Obj(id="d3", storage_path=str(path), validated_storage_path=None)
    diags = [
        _Obj(target_column=c, diagnosed_mechanism="MAR", semantic_role="continuous",
             structural_zero_warning=None, significant_drivers=[],
             n_missing=int(df[c].isna().sum()))
        for c in ("heavy", "light")
    ]
    scores = {m["column"]: m["stabilityScore"] for m in compute_column_sensitivity(dataset, diags, [])}
    assert scores["heavy"] < scores["light"]


# --------------------------------------------------------------------------
# Plausibility, fully-absent columns, and long-format strata
# --------------------------------------------------------------------------

def test_pmm_imputations_never_leave_the_observed_range():
    """Regression test.

    Chained equations sampling the unbounded normal posterior produced 453
    negative values on a CPRD extract whose observed minimum was zero. Blood
    pressure and BMI cannot be negative, so those were not plausible
    imputations. Matching draws from real observed values instead.
    """
    from app.core.imputation_engine import impute_pmm
    rng = np.random.default_rng(4)
    n = 400
    x = rng.gamma(2.0, 8.0, n) + 1.0          # strictly positive, right-skewed
    df = pd.DataFrame({"x": x, "y": x * 0.5 + rng.normal(0, 2, n)})
    df.loc[rng.choice(n, 160, replace=False), "x"] = np.nan
    observed = df["x"].dropna()

    out = impute_pmm(df, ["x", "y"], seed=1)
    assert int(out["x"].isna().sum()) == 0
    assert out["x"].min() >= observed.min()
    assert out["x"].max() <= observed.max()
    assert (out["x"] > 0).all(), "matching must not produce impossible values"


@pytest.mark.parametrize("method", ["mean", "median", "mode", "knn", "mice", "pmm", "regression"])
def test_a_fully_absent_column_does_not_crash(method):
    """Regression test.

    CPRD Aurum documents dosageid as not included in the first release, so a
    real extract contains a 100% absent column. scikit-learn drops such columns
    from its output, so assigning back raised "Columns must be same length as
    key" and failed the entire approval job. There is nothing to learn from, so
    the column must simply be left alone.
    """
    from app.core.imputation_engine import IMPUTERS
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"dosageid": [np.nan] * 60, "qty": rng.normal(20, 3, 60)})
    df.loc[:5, "qty"] = np.nan

    out = IMPUTERS[method](df, ["dosageid", "qty"])
    assert int(out["dosageid"].isna().sum()) == 60, "nothing can be inferred for it"
    assert len(out) == 60


def test_strata_detected_for_a_pooled_measurement_column():
    """Long-format data keeps one value column for several measurement types.
    Imputing it as a single variable pools quantities with no shared scale."""
    from app.core.imputation_engine import detect_measurement_strata
    rng = np.random.default_rng(6)
    frames = []
    for code, centre in [("bp", 120.0), ("bmi", 27.0), ("chol", 5.0)]:
        frames.append(pd.DataFrame({
            "code": code,
            "value": rng.normal(centre, centre * 0.05, 200),
            "other": rng.normal(0, 1, 200),
        }))
    df = pd.concat(frames, ignore_index=True)
    assert detect_measurement_strata(df, "value", ["code", "other"]) == "code"


def test_an_ordinary_predictor_is_not_mistaken_for_strata():
    """A column that merely correlates with the target must not trigger
    stratification; only a near-complete separation should."""
    from app.core.imputation_engine import detect_measurement_strata
    rng = np.random.default_rng(7)
    grp = rng.choice(["a", "b"], 400)
    df = pd.DataFrame({
        "grp": grp,
        "value": np.where(grp == "a", 10, 11) + rng.normal(0, 5, 400),
    })
    assert detect_measurement_strata(df, "value", ["grp"]) is None


def test_stratified_imputation_keeps_each_group_on_its_own_scale():
    from app.core.imputation_engine import impute_within_strata
    rng = np.random.default_rng(8)
    frames = []
    for code, centre in [("inhaler", 1.0), ("tablets", 64.0)]:
        v = rng.normal(centre, centre * 0.08, 250)
        frames.append(pd.DataFrame({"code": code, "qty": v}))
    df = pd.concat(frames, ignore_index=True)
    gaps = rng.choice(len(df), 150, replace=False)
    truth = df["qty"].copy()
    df.loc[gaps, "qty"] = np.nan

    out = impute_within_strata(df, ["qty"], stratum_col="code", method="pmm")
    for code, centre in [("inhaler", 1.0), ("tablets", 64.0)]:
        sel = out["code"] == code
        filled = out.loc[sel & df["qty"].isna(), "qty"]
        if len(filled):
            # Imputed values must sit near their own group, not near the
            # pooled mean of roughly 32.
            assert abs(filled.mean() - centre) < centre * 0.35, f"{code} drifted toward the pooled mean"


# --------------------------------------------------------------------------
# Robustness: does the estimate survive a different assumption?
# --------------------------------------------------------------------------

def _frame_with_gaps(seed=11, n=400, missing=140):
    rng = np.random.default_rng(seed)
    x = rng.normal(50, 10, n)
    df = pd.DataFrame({"x": x, "y": x * 0.4 + rng.normal(0, 3, n)})
    df.loc[rng.choice(n, missing, replace=False), "x"] = np.nan
    return df


def test_strategy_comparison_includes_the_do_nothing_baseline():
    """Complete-case analysis is the comparison that matters: it shows what the
    estimate would be if nothing had been imputed at all."""
    from app.core.sensitivity_engine import compare_imputation_strategies
    got = compare_imputation_strategies(_frame_with_gaps(), "x", ["x", "y"])
    names = [r["strategy"] for r in got]
    assert "complete_case" in names
    assert "pmm" in names
    assert "__summary__" in names


def test_strategy_comparison_reports_how_far_the_estimate_travels():
    from app.core.sensitivity_engine import compare_imputation_strategies
    got = compare_imputation_strategies(_frame_with_gaps(), "x", ["x", "y"])
    summary = next(r for r in got if r["strategy"] == "__summary__")
    lo, hi = summary["estimate_range"]
    assert lo <= hi
    assert summary["spread"] == pytest.approx(hi - lo, abs=1e-6)
    assert summary["spread_pct_of_estimate"] >= 0


def test_mnar_sweep_is_monotonic_and_centres_on_the_mar_assumption():
    """Shifting the unobserved values upward must raise the estimate, and delta
    zero must be the assumption the pipeline actually uses."""
    from app.core.sensitivity_engine import mnar_delta_sweep
    got = mnar_delta_sweep(_frame_with_gaps(), "x", ["x", "y"])
    estimates = [g["estimate"] for g in got]
    assert estimates == sorted(estimates), "a higher assumed value must raise the estimate"
    centre = next(g for g in got if g["delta_sd"] == 0.0)
    assert "MAR" in centre["assumption"]


def test_sweep_is_empty_when_there_is_nothing_missing():
    """With no gaps there is no assumption to vary, so no sweep is reported."""
    from app.core.sensitivity_engine import mnar_delta_sweep
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    assert mnar_delta_sweep(df, "x", ["x", "y"]) == []


def test_robustness_is_measured_without_any_ground_truth():
    """The point of this analysis: it needs no planted answer, so it works on a
    real dataset where the true values are unknowable."""
    from app.core.sensitivity_engine import compare_imputation_strategies, mnar_delta_sweep
    df = _frame_with_gaps()
    assert compare_imputation_strategies(df, "x", ["x", "y"])
    assert mnar_delta_sweep(df, "x", ["x", "y"])
