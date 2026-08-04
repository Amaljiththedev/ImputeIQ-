"""
missingness_profiling.py

Computes per-column missingness statistics.
"""

from __future__ import annotations

import pandas as pd


def profile_missingness(df: pd.DataFrame) -> list[dict]:
    """Compute per-column missingness statistics."""
    total_rows = len(df)
    profile = []
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        pct_missing = round((n_missing / total_rows) * 100, 2) if total_rows > 0 else 0.0
        profile.append({
            "column": col,
            "missing_count": n_missing,
            "missing_pct": pct_missing
        })
    return profile
