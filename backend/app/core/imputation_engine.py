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
    out = df.copy()
    imputer = IterativeImputer(
        estimator=BayesianRidge(),
        max_iter=50,
        tol=1e-2,
        random_state=seed,
        sample_posterior=False,
    )
    out[cols] = imputer.fit_transform(out[cols])
    return out


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
