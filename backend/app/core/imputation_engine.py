"""
imputation_engine.py

Implements various imputation strategies (mean, median, mode, KNN, MICE,
regression, zero, and flag-only) for use by method_router.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer, KNNImputer, SimpleImputer
from sklearn.linear_model import BayesianRidge, LinearRegression

RANDOM_SEED = 42


def impute_mean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    imputer = SimpleImputer(strategy="mean")
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_median(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    imputer = SimpleImputer(strategy="median")
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_mode(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Most-frequent-value imputation. Correct choice for CATEGORICAL /
    lookup-coded columns (e.g. quantunitid, patienttypeid, medcodeid) where
    an arithmetic median or mean would be meaningless."""
    out = df.copy()
    imputer = SimpleImputer(strategy="most_frequent")
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_knn(df: pd.DataFrame, cols: list[str], n_neighbors: int = 5) -> pd.DataFrame:
    out = df.copy()
    imputer = KNNImputer(n_neighbors=n_neighbors)
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_mice(df: pd.DataFrame, cols: list[str], seed: int = RANDOM_SEED) -> pd.DataFrame:
    """One completed dataset drawn from the posterior predictive distribution.

    sample_posterior=True is what makes this chained equations rather than
    deterministic conditional-mean filling. With it False (the previous
    setting) every gap was filled with the model's point prediction, which
    collapses variance and makes the result reproducible-but-wrong: it looked
    like MICE and was labelled MICE, but carried none of MICE's uncertainty.

    This still returns a SINGLE dataset. Multiple imputation in Rubin's sense
    requires several, analysed separately and pooled -- see
    impute_mice_multiple() and pool_rubin(). Use those when reporting
    estimates and standard errors.
    """
    out = df.copy()
    imputer = IterativeImputer(
        estimator=BayesianRidge(),
        max_iter=50,
        tol=1e-2,
        random_state=seed,
        sample_posterior=True,
    )
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_mice_multiple(
    df: pd.DataFrame,
    cols: list[str],
    m: int = 5,
    seed: int = RANDOM_SEED,
) -> list[pd.DataFrame]:
    """Generate m completed datasets, each a separate posterior draw.

    Each uses a different random_state, so the imputations differ. The spread
    between them is the information single imputation throws away, and it is
    what pool_rubin() turns into an honest standard error.
    """
    if m < 2:
        raise ValueError("multiple imputation needs m >= 2 datasets")
    return [impute_mice(df, cols, seed=seed + i) for i in range(m)]


def pool_rubin(estimates: list[float], variances: list[float] | None = None) -> dict:
    """Combine estimates across imputations using Rubin's rules.

    Given Q_i (the estimate from imputation i) and optionally U_i (its sampling
    variance):

        Qbar = mean(Q_i)                          pooled estimate
        Ubar = mean(U_i)                          within-imputation variance
        B    = var(Q_i, ddof=1)                   between-imputation variance
        T    = Ubar + (1 + 1/m) * B               total variance
        FMI  ~ (1 + 1/m) * B / T                  fraction of missing information

    B is the term single imputation cannot produce, because with one dataset
    there is nothing to vary. Reporting T instead of Ubar is what stops
    standard errors being too small.

    CONSORT 2025 item 21c asks for the number of imputed datasets and how
    results were combined; m and these components are that answer.
    """
    m = len(estimates)
    if m < 2:
        raise ValueError("pooling needs at least 2 imputations")

    q = np.asarray(estimates, dtype=float)
    qbar = float(q.mean())
    between = float(q.var(ddof=1))
    within = float(np.mean(np.asarray(variances, dtype=float))) if variances else 0.0

    total = within + (1.0 + 1.0 / m) * between
    fmi = ((1.0 + 1.0 / m) * between / total) if total > 0 else 0.0

    return {
        "m": m,
        "pooled_estimate": qbar,
        "within_variance": within,
        "between_variance": between,
        "total_variance": total,
        "standard_error": float(np.sqrt(total)) if total > 0 else 0.0,
        "fraction_missing_information": float(min(1.0, max(0.0, fmi))),
    }


def pool_column_mean(imputations: list[pd.DataFrame], col: str) -> dict:
    """Rubin-pooled mean of `col` across a set of completed datasets.

    Each imputation contributes its column mean as Q_i and the sampling
    variance of that mean (s^2/n) as U_i.
    """
    estimates, variances = [], []
    for d in imputations:
        s = pd.to_numeric(d[col], errors="coerce").dropna()
        if s.empty:
            continue
        estimates.append(float(s.mean()))
        variances.append(float(s.var(ddof=1) / len(s)) if len(s) > 1 else 0.0)
    return pool_rubin(estimates, variances)


def impute_regression(df: pd.DataFrame, cols: list[str], seed: int = RANDOM_SEED) -> pd.DataFrame:
    out = df.copy()
    imputer = IterativeImputer(
        estimator=LinearRegression(),
        max_iter=1,
        random_state=seed,
        sample_posterior=False,
    )
    out[cols] = imputer.fit_transform(out[cols])
    return out


def impute_zero(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    out[cols] = out[cols].fillna(0)
    return out


def impute_flag(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Deliberate NO-OP imputer for IDENTIFIER columns. Fabricating a median/
    mean/mode value for a patient/staff/observation ID would create a false
    link to a record that doesn't exist, so this leaves the value as NaN and
    adds a boolean '<col>_missing' indicator column instead, for downstream
    flagging/manual review purposes."""
    out = df.copy()
    for col in cols:
        flag_col = f"{col}_missing"
        out[flag_col] = out[col].isna()
    return out


IMPUTERS = {
    "mean": impute_mean,
    "median": impute_median,
    "mode": impute_mode,
    "knn": impute_knn,
    "mice": impute_mice,
    "regression": impute_regression,
    "zero": impute_zero,
    "flag_only": impute_flag,
}


def run_imputation(df: pd.DataFrame, method: str, cols: list[str]) -> pd.DataFrame:
    """Convenience wrapper to execute a named imputer."""
    method_key = method.lower()
    if method_key not in IMPUTERS:
        raise ValueError(f"Unknown imputation method: {method}")
    return IMPUTERS[method_key](df, cols)
