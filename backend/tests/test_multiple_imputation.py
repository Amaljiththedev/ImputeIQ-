"""Multiple imputation and Rubin pooling.

These pin the distinction the tool previously blurred: chained equations run
once is not multiple imputation, and only the multi-dataset path can produce a
standard error that accounts for uncertainty about the missing values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.imputation_engine import (
    impute_mice,
    impute_mice_multiple,
    pool_column_mean,
    pool_rubin,
)


@pytest.fixture
def gapped_frame():
    rng = np.random.default_rng(7)
    n = 300
    x = rng.normal(50, 10, n)
    df = pd.DataFrame({"x": x, "y": 0.6 * x + rng.normal(0, 4, n)})
    df.loc[rng.choice(n, 90, replace=False), "x"] = np.nan
    return df


def test_mice_draws_from_the_posterior_rather_than_the_mean(gapped_frame):
    """Regression test.

    With sample_posterior=False every gap received the model's point
    prediction, so two runs with different seeds were identical. Genuine
    chained equations must vary between draws.
    """
    a = impute_mice(gapped_frame, ["x", "y"], seed=1)
    b = impute_mice(gapped_frame, ["x", "y"], seed=2)
    gaps = gapped_frame["x"].isna()
    assert not np.allclose(a.loc[gaps, "x"], b.loc[gaps, "x"]), (
        "different seeds produced identical imputations -- this is not a posterior draw"
    )


def test_same_seed_is_reproducible(gapped_frame):
    a = impute_mice(gapped_frame, ["x", "y"], seed=11)
    b = impute_mice(gapped_frame, ["x", "y"], seed=11)
    assert np.allclose(a["x"], b["x"])


def test_multiple_imputation_returns_m_distinct_datasets(gapped_frame):
    sets = impute_mice_multiple(gapped_frame, ["x", "y"], m=5, seed=3)
    assert len(sets) == 5
    gaps = gapped_frame["x"].isna()
    filled = [d.loc[gaps, "x"].to_numpy() for d in sets]
    assert all(not np.allclose(filled[0], f) for f in filled[1:])
    for d in sets:
        assert int(d["x"].isna().sum()) == 0


def test_multiple_imputation_rejects_m_below_two(gapped_frame):
    with pytest.raises(ValueError):
        impute_mice_multiple(gapped_frame, ["x", "y"], m=1)


def test_observed_values_survive_every_imputation(gapped_frame):
    observed = gapped_frame["x"].notna()
    for d in impute_mice_multiple(gapped_frame, ["x", "y"], m=3, seed=5):
        assert np.allclose(gapped_frame.loc[observed, "x"], d.loc[observed, "x"])


def test_pooling_recovers_between_imputation_variance():
    pooled = pool_rubin([10.0, 10.4, 9.6, 10.2, 9.8], [0.5] * 5)
    assert pooled["m"] == 5
    assert pooled["pooled_estimate"] == pytest.approx(10.0, abs=1e-9)
    assert pooled["between_variance"] > 0
    # Total variance must exceed the within-imputation variance alone; that gap
    # is exactly what single imputation omits.
    assert pooled["total_variance"] > pooled["within_variance"]
    assert 0.0 <= pooled["fraction_missing_information"] <= 1.0


def test_identical_estimates_mean_no_between_variance():
    pooled = pool_rubin([7.0, 7.0, 7.0], [0.25] * 3)
    assert pooled["between_variance"] == pytest.approx(0.0)
    assert pooled["total_variance"] == pytest.approx(pooled["within_variance"])
    assert pooled["fraction_missing_information"] == pytest.approx(0.0)


def test_pooling_needs_at_least_two_imputations():
    with pytest.raises(ValueError):
        pool_rubin([1.0])


def test_pooled_standard_error_exceeds_the_single_imputation_one(gapped_frame):
    """The practical consequence: reporting from one dataset understates the
    standard error, because it counts no uncertainty about the filled values."""
    sets = impute_mice_multiple(gapped_frame, ["x", "y"], m=5, seed=9)
    pooled = pool_column_mean(sets, "x")

    single = sets[0]["x"]
    single_se = float(single.std(ddof=1) / np.sqrt(len(single)))

    assert pooled["between_variance"] > 0
    assert pooled["standard_error"] > single_se


def test_pool_column_mean_reports_m(gapped_frame):
    pooled = pool_column_mean(impute_mice_multiple(gapped_frame, ["x", "y"], m=4, seed=4), "x")
    assert pooled["m"] == 4
    assert pooled["standard_error"] > 0
