"""
synthetic_missingness.py

Injects synthetic MCAR, MAR, and MNAR missingness into ground-truth datasets
(such as cardio_train_ground_truth.csv or patient_records_clean.csv).

Design notes for cardio_train_ground_truth.csv (5,000 rows):
- weight:      MCAR (target: 8.0%)  -> Uniform random mask
- alco:        MCAR (target: 5.0%)  -> Uniform random mask
- ap_hi:       MAR  (target: 15.0%) -> Driven by age (older patients more likely missing)
- gluc:        MAR  (target: 10.0%) -> Driven by active (active=0 more likely missing)
- cholesterol: MNAR (target: 12.0%) -> Self-masking (higher true cholesterol more likely missing)
- smoke:       MCAR (target: 3.0%)  -> Uniform random mask

Usage:
    python -m app.core.synthetic_missingness
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "synthetic"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

DESKTOP_CARDIO_PATH = DATA_DIR / "cardio_train.csv" if (DATA_DIR / "cardio_train.csv").exists() else Path("C:/Users/amalj/OneDrive/Desktop/cardio_train.csv")
CARDIO_GROUND_TRUTH_PATH = DATA_DIR / "cardio_train_ground_truth.csv"
PATIENT_RECORDS_PATH = DATA_DIR / "patient_records_clean.csv"

RANDOM_SEED = 123


# ---------------------------------------------------------------------------
# Masking functions
# ---------------------------------------------------------------------------

def inject_mcar(df: pd.DataFrame, column: str, rate: float, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Missing Completely At Random: uniform random masking, independent of
    any other value in the row."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    n_missing = int(round(rate * len(out)))
    idx = rng.choice(out.index, size=n_missing, replace=False)
    out.loc[idx, column] = np.nan
    return out


def inject_mar(
    df: pd.DataFrame,
    target_col: str,
    driver_col: str,
    rate: float,
    weights: dict[Any, float] | None = None,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Missing At Random: masking probability depends on another OBSERVED
    column (driver_col), not on the target value itself."""
    rng = np.random.default_rng(seed)
    out = df.copy()

    if weights is not None:
        row_weights = out[driver_col].map(weights).fillna(1.0).to_numpy(dtype=float)
    else:
        # If no categorical weights provided, or continuous driver column (e.g. age),
        # rank-based weighting where higher values of driver -> higher probability
        ranks = out[driver_col].rank(method="average")
        row_weights = ranks.to_numpy(dtype=float)

    probs = row_weights / row_weights.sum()
    n_missing = int(round(rate * len(out)))
    idx = rng.choice(out.index, size=n_missing, replace=False, p=probs)
    out.loc[idx, target_col] = np.nan
    return out


def inject_mnar(df: pd.DataFrame, column: str, rate: float, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Missing Not At Random: masking probability depends on the target
    column's OWN value (self-masking) -- higher values more likely missing."""
    rng = np.random.default_rng(seed)
    out = df.copy()

    # Rank-based weighting: higher value -> higher rank -> higher probability.
    ranks = out[column].rank(method="average")
    weights = ranks.to_numpy(dtype=float)
    probs = weights / weights.sum()

    n_missing = int(round(rate * len(out)))
    idx = rng.choice(out.index, size=n_missing, replace=False, p=probs)
    out.loc[idx, column] = np.nan
    return out


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------

@dataclass
class MaskRecord:
    mechanism: str
    target_col: str
    rate: float
    n_missing: int
    pct_missing_actual: float
    output_file: str
    driver_col: str | None = None
    rule: str = ""
    extra: dict = field(default_factory=dict)


def verify_mask(original: pd.DataFrame, masked: pd.DataFrame, column: str) -> dict:
    """Sanity checks: confirms masking landed only in the target column,
    and that no other columns / rows were altered."""
    other_cols = [c for c in original.columns if c != column]
    unchanged_elsewhere = original[other_cols].equals(masked[other_cols])
    n_missing = int(masked[column].isna().sum())
    return {
        "unchanged_elsewhere": bool(unchanged_elsewhere),
        "n_missing": n_missing,
        "pct_missing_actual": round(n_missing / len(masked) * 100, 2),
    }


def ensure_cardio_ground_truth(n_rows: int = 5000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Loads cardio_train.csv from Desktop if cardio_train_ground_truth.csv doesn't exist,
    samples `n_rows` cleanly, converts age from days to years, and saves the clean ground truth."""
    if CARDIO_GROUND_TRUTH_PATH.exists():
        df = pd.read_csv(CARDIO_GROUND_TRUTH_PATH)
        if len(df) == n_rows:
            return df

    if not DESKTOP_CARDIO_PATH.exists():
        raise FileNotFoundError(f"Source file {DESKTOP_CARDIO_PATH} not found.")

    raw_df = pd.read_csv(DESKTOP_CARDIO_PATH, sep=";")
    # Filter out obvious measurement errors/outliers so ground truth is clean
    clean = raw_df[
        (raw_df["ap_hi"] >= 60) & (raw_df["ap_hi"] <= 240) &
        (raw_df["ap_lo"] >= 40) & (raw_df["ap_lo"] <= 160) &
        (raw_df["ap_hi"] > raw_df["ap_lo"]) &
        (raw_df["height"] >= 130) & (raw_df["height"] <= 210) &
        (raw_df["weight"] >= 35) & (raw_df["weight"] <= 180)
    ].copy()

    sampled = clean.sample(n=n_rows, random_state=seed).reset_index(drop=True)
    # Convert age from days to integer years
    if sampled["age"].mean() > 1000:
        sampled["age"] = (sampled["age"] / 365.25).round().astype(int)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sampled.to_csv(CARDIO_GROUND_TRUTH_PATH, index=False)
    print(f"Generated clean ground-truth dataset ({n_rows} rows) at {CARDIO_GROUND_TRUTH_PATH.resolve()}")
    return sampled


# ---------------------------------------------------------------------------
# Dynamic Specification Generator & Pipeline Runner
# ---------------------------------------------------------------------------

def generate_dynamic_specifications(df: pd.DataFrame, seed: int = RANDOM_SEED) -> tuple[list[dict], dict[str, dict]]:
    """Dynamically inspects ALL columns of any dataframe (`df`) to assign appropriate
    academic ground-truth mechanisms (`none`, `MCAR`, `MAR`, `MNAR`).
    If the dataset has exact classic cardio_train columns, preserves standard academic
    baseline specs while enabling dynamic generation for any other uploaded dataset.
    """
    cols = df.columns.tolist()
    columns_spec: dict[str, dict] = {}
    specifications: list[dict] = []

    # Check if exact cardio_train academic columns exist
    classic_cardio_cols = {"id", "weight", "alco", "ap_hi", "gluc", "cholesterol", "smoke", "cardio", "height", "gender", "ap_lo"}
    if classic_cardio_cols.issubset(set(cols)):
        # Preserve classic academic benchmark rules for cardio_train
        columns_spec = {
            "id": {"mechanism": "none", "rule": "Identifier column, never corrupted."},
            "cardio": {"mechanism": "none", "rule": "Target/label column, never corrupted."},
            "height": {"mechanism": "none", "rule": "Fully observed control column, used as a clean predictor in diagnosis tests."},
            "gender": {"mechanism": "none", "rule": "Fully observed control column."},
            "ap_lo": {"mechanism": "none", "rule": "Fully observed control column."},
        }
        specifications = [
            {"col": "weight", "mech": "MCAR", "rate": 0.08, "driver": None, "rule": "Uniform random mask, independent of all other variables."},
            {"col": "alco", "mech": "MCAR", "rate": 0.05, "driver": None, "rule": "Uniform random mask, independent of all other variables."},
            {"col": "ap_hi", "mech": "MAR", "rate": 0.15, "driver": "age", "weights": None, "rule": "Missingness probability increases with patient age (older patients more likely to skip BP measurement at routine visits)."},
            {"col": "gluc", "mech": "MAR", "rate": 0.10, "driver": "active", "weights": {0: 3.0, 1: 1.0}, "rule": "Missingness probability is higher for physically inactive patients (active=0), reflecting lower routine screening uptake."},
            {"col": "cholesterol", "mech": "MNAR", "rate": 0.12, "driver": None, "rule": "Missingness probability increases with the patient's own true cholesterol level (higher cholesterol -> more likely missing), simulating avoidance/non-follow-up bias. Cannot be detected from observed data alone."},
            {"col": "smoke", "mech": "MCAR", "rate": 0.03, "driver": None, "rule": "Uniform random mask, independent of all other variables."},
        ]
        return specifications, columns_spec

    # Otherwise, dynamically inspect and classify ALL columns across the dataset
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in cols if c not in num_cols]

    # 1. Identify IDs and target columns to keep clean
    for col in cols:
        lower = col.lower()
        if lower in ("id", "patient_id", "record_id", "index", "key") or lower.endswith("_id") or (col in num_cols and df[col].nunique() == len(df)):
            columns_spec[col] = {"mechanism": "none", "rule": "Identifier/key column, never corrupted."}
        elif lower in ("target", "label", "outcome", "class", "cardio", "status", "death", "deceased"):
            columns_spec[col] = {"mechanism": "none", "rule": "Target/label column, never corrupted."}

    candidate_cols = [c for c in cols if c not in columns_spec]

    # Keep 1 or 2 observed continuous predictor columns clean for MAR driver testing
    clean_predictors = []
    for col in candidate_cols:
        if col in num_cols and df[col].nunique() > 10 and len(clean_predictors) < 2:
            clean_predictors.append(col)
            columns_spec[col] = {"mechanism": "none", "rule": "Fully observed control predictor column."}

    feature_cols = [c for c in candidate_cols if c not in columns_spec]
    if not feature_cols:
        return specifications, columns_spec

    # Dynamically cycle MCAR, MAR, MNAR across all eligible feature columns
    mechanisms = ["MCAR", "MAR", "MNAR"]
    rates = [0.08, 0.12, 0.15, 0.05, 0.10]
    all_observed_drivers = [c for c in cols if c in columns_spec and c != "id" and df[c].nunique() > 1]
    if not all_observed_drivers:
        all_observed_drivers = clean_predictors or [c for c in cols if c != "id" and df[c].nunique() > 1]

    for i, col in enumerate(feature_cols):
        mech = mechanisms[i % len(mechanisms)]
        rate = rates[i % len(rates)]

        if mech == "MCAR":
            specifications.append({
                "col": col,
                "mech": "MCAR",
                "rate": rate,
                "driver": None,
                "rule": f"Uniform random mask ({int(rate*100)}%), independent of all other variables.",
            })
        elif mech == "MAR":
            driver = all_observed_drivers[i % len(all_observed_drivers)] if all_observed_drivers else None
            if not driver or driver == col:
                # Fallback to MCAR if no valid driver available
                specifications.append({
                    "col": col,
                    "mech": "MCAR",
                    "rate": rate,
                    "driver": None,
                    "rule": f"Uniform random mask ({int(rate*100)}%), independent of all other variables.",
                })
            else:
                weights = None
                if df[driver].nunique() <= 5:
                    unique_vals = df[driver].dropna().unique()
                    weights = {val: (3.0 if idx == 0 else 1.0) for idx, val in enumerate(unique_vals)}
                specifications.append({
                    "col": col,
                    "mech": "MAR",
                    "rate": rate,
                    "driver": driver,
                    "weights": weights,
                    "rule": f"Missingness probability ({int(rate*100)}%) is driven by observed column '{driver}'.",
                })
        elif mech == "MNAR":
            specifications.append({
                "col": col,
                "mech": "MNAR",
                "rate": rate,
                "driver": None,
                "rule": f"Self-masking missingness ({int(rate*100)}%): higher true values of '{col}' are more likely to be missing.",
            })

    return specifications, columns_spec


def run_dynamic_pipeline(
    source_path: Path | None = None,
    output_prefix: str | None = None,
    n_rows: int | None = None,
    seed: int = RANDOM_SEED,
) -> dict:
    """Dynamically inspects and injects synthetic missingness across ALL feature columns
    of any provided dataset (`source_path`), producing individual files and a combined
    corrupted dataset (`{output_prefix}_corrupted_combined.csv`) with updated manifest.json.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if source_path is not None and source_path.exists():
        df = pd.read_csv(source_path, sep=None, engine="python")
        if n_rows and len(df) > n_rows:
            df = df.sample(n=n_rows, random_state=seed).reset_index(drop=True)
        source_name = source_path.name
        prefix = output_prefix or source_path.stem
    else:
        df = ensure_cardio_ground_truth(n_rows=5000, seed=seed)
        source_name = "cardio_train_ground_truth.csv"
        prefix = output_prefix or "cardio_train"

    specifications, columns_spec = generate_dynamic_specifications(df, seed=seed)

    manifest: list[MaskRecord] = []
    combined_df = df.copy()

    for spec in specifications:
        col = spec["col"]
        mech = spec["mech"]
        rate = spec["rate"]
        driver = spec["driver"]
        rule = spec["rule"]
        weights = spec.get("weights")

        if col not in df.columns:
            continue

        if mech == "MCAR":
            masked_df = inject_mcar(df, col, rate, seed=seed)
            combined_df = inject_mcar(combined_df, col, rate, seed=seed)
        elif mech == "MAR" and driver and driver in df.columns:
            masked_df = inject_mar(df, col, driver, rate, weights=weights, seed=seed)
            combined_df = inject_mar(combined_df, col, driver, rate, weights=weights, seed=seed)
        elif mech == "MNAR":
            masked_df = inject_mnar(df, col, rate, seed=seed)
            combined_df = inject_mnar(combined_df, col, rate, seed=seed)
        else:
            masked_df = inject_mcar(df, col, rate, seed=seed)
            combined_df = inject_mcar(combined_df, col, rate, seed=seed)
            mech = "MCAR"

        check = verify_mask(df, masked_df, col)
        out_file = f"{prefix}_{col}_{mech.lower()}.csv"
        masked_df.to_csv(OUTPUT_DIR / out_file, index=False)

        manifest.append(
            MaskRecord(
                mechanism=mech,
                target_col=col,
                rate=rate,
                n_missing=check["n_missing"],
                pct_missing_actual=check["pct_missing_actual"],
                output_file=out_file,
                driver_col=driver,
                rule=rule,
                extra={"unchanged_elsewhere": check["unchanged_elsewhere"]},
            )
        )
        print(f"[{mech}] {col:16s} -> {out_file} ({check['n_missing']} missing, {check['pct_missing_actual']}%)")

    # Save combined multi-column corrupted dataset
    combined_file = f"{prefix}_corrupted_combined.csv"
    combined_df.to_csv(OUTPUT_DIR / combined_file, index=False)
    print(f"\nSaved dynamic combined multi-column dataset to {OUTPUT_DIR / combined_file}")

    manifest_data = {
        "seed": seed,
        "source": source_name,
        "n_rows": len(df),
        "columns": {
            **columns_spec,
            **{
                m.target_col: {
                    "mechanism": m.mechanism,
                    "target_missing_rate": m.rate,
                    "actual_missing_rate": round(m.pct_missing_actual / 100.0, 4),
                    **({"driver_column": m.driver_col} if m.driver_col else {}),
                    "rule": m.rule,
                    "output_file": m.output_file,
                }
                for m in manifest
            },
        },
        "generated_files": [
            {
                "mechanism": m.mechanism,
                "target_column": m.target_col,
                "driver_column": m.driver_col,
                "requested_rate": m.rate,
                "actual_missing_count": m.n_missing,
                "actual_missing_pct": m.pct_missing_actual,
                "output_file": m.output_file,
                **m.extra,
            }
            for m in manifest
        ],
        "combined_file": combined_file,
    }

    MANIFEST_PATH.write_text(json.dumps(manifest_data, indent=2))
    print(f"\nDynamic manifest written to {MANIFEST_PATH.resolve()}")
    return manifest_data


def run_cardio_pipeline() -> None:
    run_dynamic_pipeline(source_path=None, output_prefix="cardio_train", seed=RANDOM_SEED)


def main() -> None:
    if DESKTOP_CARDIO_PATH.exists() or CARDIO_GROUND_TRUTH_PATH.exists():
        run_cardio_pipeline()
    else:
        if not PATIENT_RECORDS_PATH.exists():
            raise FileNotFoundError("Neither cardio_train.csv nor patient_records_clean.csv found.")
        print(f"Running dynamic pipeline on {PATIENT_RECORDS_PATH.resolve()}...")
        run_dynamic_pipeline(source_path=PATIENT_RECORDS_PATH, output_prefix="patient_records")


if __name__ == "__main__":
    main()