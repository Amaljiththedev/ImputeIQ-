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
