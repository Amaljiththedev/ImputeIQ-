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


def imputable_columns(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Columns that have at least one observed value to learn from.

    A column that is entirely missing cannot be imputed: there is nothing to
    take a mean, mode or donor from. scikit-learn's imputers silently DROP such
    columns from their output, so assigning the result back raises
    "Columns must be same length as key" and the whole job fails.

    This is not hypothetical. CPRD Aurum's Drug Issue table documents dosageid
    as "not included in first release", so a real extract contains a column
    that is 100% absent, and it crashed the approval step.
    """
    return [c for c in cols if c in df.columns and df[c].notna().any()]


def _fit_on_usable(df: pd.DataFrame, cols: list[str], imputer) -> pd.DataFrame:
    """Run a scikit-learn imputer over only the columns it can actually learn
    from, leaving fully-missing columns untouched rather than failing."""
    out = df.copy()
    usable = imputable_columns(df, cols)
    if not usable:
        return out
    out[usable] = imputer.fit_transform(out[usable])
    return out


def impute_mean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return _fit_on_usable(df, cols, SimpleImputer(strategy="mean"))


def impute_median(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return _fit_on_usable(df, cols, SimpleImputer(strategy="median"))


def impute_mode(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Most-frequent-value imputation. Correct choice for CATEGORICAL /
    lookup-coded columns (e.g. quantunitid, patienttypeid, medcodeid) where
    an arithmetic median or mean would be meaningless."""
    return _fit_on_usable(df, cols, SimpleImputer(strategy="most_frequent"))


def impute_knn(df: pd.DataFrame, cols: list[str], n_neighbors: int = 5) -> pd.DataFrame:
    return _fit_on_usable(df, cols, KNNImputer(n_neighbors=n_neighbors))


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
    return _fit_on_usable(df, cols, IterativeImputer(
        estimator=BayesianRidge(),
        max_iter=50,
        tol=1e-2,
        random_state=seed,
        sample_posterior=True,
    ))


def impute_pmm(
    df: pd.DataFrame,
    cols: list[str],
    k: int = 5,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Predictive mean matching.

    A chained model predicts every row, then each missing entry is filled with
    a value actually observed in one of the k rows whose prediction is closest
    to its own. Because every imputation is a real observed value, the result
    cannot leave the observed range.

    This matters here. Drawing from the unbounded normal posterior
    (impute_mice) produced 453 negative clinical measurements on a CPRD extract
    whose observed minimum was zero, and shifted the mean from 53.9 to 34.1.
    Blood pressure and BMI cannot be negative, so those draws were not
    plausible imputations however well the model fitted. van Buuren (2018,
    sec. 3.4) recommends matching for exactly this reason, and it is the
    default method in the mice package.
    """
    out = df.copy()
    rng = np.random.default_rng(seed)

    # Predictions for every row, from the same chained model used elsewhere.
    predicted = impute_mice(df, cols, seed=seed)

    for col in cols:
        observed_mask = df[col].notna()
        missing_mask = df[col].isna()
        if not missing_mask.any() or observed_mask.sum() == 0:
            continue

        donors_y = pd.to_numeric(df.loc[observed_mask, col], errors="coerce").to_numpy(dtype=float)
        donors_pred = pd.to_numeric(predicted.loc[observed_mask, col], errors="coerce").to_numpy(dtype=float)
        targets_pred = pd.to_numeric(predicted.loc[missing_mask, col], errors="coerce").to_numpy(dtype=float)

        valid = ~np.isnan(donors_y) & ~np.isnan(donors_pred)
        donors_y, donors_pred = donors_y[valid], donors_pred[valid]
        if donors_y.size == 0:
            continue

        neighbours = min(k, donors_y.size)
        drawn = np.empty(targets_pred.shape, dtype=float)
        for i, p in enumerate(targets_pred):
            if np.isnan(p):
                drawn[i] = float(rng.choice(donors_y))
                continue
            # k closest donors by predicted value, then one of them at random.
            nearest = np.argpartition(np.abs(donors_pred - p), neighbours - 1)[:neighbours]
            drawn[i] = float(donors_y[rng.integers(0, neighbours)] if neighbours == 1
                             else donors_y[rng.choice(nearest)])
        out.loc[missing_mask, col] = drawn

    return out


def detect_measurement_strata(
    df: pd.DataFrame,
    target_col: str,
    candidate_cols: list[str],
    min_eta_squared: float = 0.5,
    max_levels: int = 50,
) -> str | None:
    """Find a column that splits `target_col` into incommensurable groups.

    Long-format clinical data keeps one value column for every kind of
    measurement, distinguished by a code. CPRD Aurum's Observation table is
    built this way: `value` holds blood pressures near 120, BMI near 27,
    cholesterol near 5 and HbA1c near 42, told apart only by `medcodeid`.
    Imputing that column as one variable regresses toward a mean computed
    across quantities that share no scale, which inflated every measurement
    type on a real extract regardless of the method used.

    Detection is by eta squared, the share of the target's variance lying
    between groups rather than within them. A value near 1 means the groups
    barely overlap, which is the signature of pooled measurement types rather
    than of an ordinary predictor.

    Returns the strongest such column, or None when no column splits the
    target that sharply.
    """
    y_all = pd.to_numeric(df[target_col], errors="coerce")
    observed = y_all.notna()
    if observed.sum() < 20:
        return None

    y = y_all[observed]
    total_ss = float(((y - y.mean()) ** 2).sum())
    if total_ss <= 0:
        return None

    best_col, best_eta = None, 0.0
    for col in candidate_cols:
        if col == target_col or col not in df.columns:
            continue
        groups = df.loc[observed, col]
        n_levels = int(groups.nunique(dropna=True))
        if n_levels < 2 or n_levels > max_levels:
            continue

        between_ss = 0.0
        for _, idx in groups.groupby(groups, dropna=True).groups.items():
            g = y.loc[idx]
            if len(g) == 0:
                continue
            between_ss += len(g) * (float(g.mean()) - float(y.mean())) ** 2

        eta_squared = between_ss / total_ss
        if eta_squared > best_eta:
            best_col, best_eta = col, eta_squared

    return best_col if best_eta >= min_eta_squared else None


def impute_within_strata(
    df: pd.DataFrame,
    cols: list[str],
    stratum_col: str,
    method: str = "pmm",
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Impute each group separately, so values are never borrowed across
    measurement types. Groups too small to model fall back to their own
    median, which is still confined to the correct measurement."""
    out = df.copy()
    imputer = IMPUTERS[method]

    for level, idx in df.groupby(stratum_col, dropna=False).groups.items():
        block = df.loc[idx]
        if len(block) < 5:
            for col in cols:
                observed = pd.to_numeric(block[col], errors="coerce").dropna()
                if not observed.empty:
                    out.loc[idx, col] = block[col].fillna(observed.median())
            continue
        try:
            filled = imputer(block, cols, seed=seed) if method in ("pmm", "mice", "regression") \
                else imputer(block, cols)
            for col in cols:
                out.loc[idx, col] = filled[col]
        except Exception:
            for col in cols:
                observed = pd.to_numeric(block[col], errors="coerce").dropna()
                if not observed.empty:
                    out.loc[idx, col] = block[col].fillna(observed.median())

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
    return _fit_on_usable(df, cols, IterativeImputer(
        estimator=LinearRegression(),
        max_iter=1,
        random_state=seed,
        sample_posterior=False,
    ))


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
    "pmm": impute_pmm,
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
