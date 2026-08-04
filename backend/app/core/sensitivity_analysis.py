"""
sensitivity_analysis.py

Sensitivity analysis for the ImputeIQ pipeline, covering three angles:

1. RATE SENSITIVITY
   How does imputation error (nRMSE) change as the missingness rate
   increases (10% -> 20% -> 30%), per method and per mechanism? Built
   directly from the existing Phase 3 results
   (data/synthetic/imputation_results.csv) -- no new computation needed.

2. MISDIAGNOSIS COST
   Phase 2 established that true MCAR and true MNAR data are
   INDISTINGUISHABLE from observed data alone, so the diagnosis pipeline
   reports both as "Ambiguous (MCAR/MNAR)" and routes them conservatively
   (median, low-confidence) rather than risking a wrong confident guess.
   This section quantifies the actual accuracy COST of that conservative
   choice: for genuinely MCAR data, how much worse is the safe "Ambiguous"
   routing (median) compared to what the empirically-best MCAR method
   (MICE) would have achieved, if the mechanism were somehow known for
   certain? This is the price paid for honesty over false confidence.

3. MICE SEED SENSITIVITY
   MICE (via sklearn's IterativeImputer with BayesianRidge) has stochastic
   elements. This section re-runs MICE imputation multiple times with
   different random seeds on the same masked file, and measures how much
   the imputed VALUES and resulting nRMSE vary run-to-run. Low variation
   supports treating a single MICE run as representative; high variation
   would be an important caveat for any dissertation claim based on one
   MICE run.

Usage:
    python sensitivity_analysis.py
Reads:
    data/patient_records_clean.csv
    data/synthetic/manifest.json
    data/synthetic/imputation_results.csv   (from impute_engine.py)
Writes:
    data/synthetic/sensitivity_rate.csv
    data/synthetic/sensitivity_rate.png
    data/synthetic/sensitivity_misdiagnosis_cost.json
    data/synthetic/sensitivity_mice_seed.csv
    data/synthetic/sensitivity_mice_seed.png
    data/synthetic/sensitivity_report.json   (combined summary)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless -- no display needed, just save PNGs
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from impute_engine import IMPUTERS, NUMERIC_COLS, score_imputation

DATA_DIR = Path("data/synthetic")
GROUND_TRUTH_PATH = Path("data/patient_records_clean.csv")
MANIFEST_PATH = DATA_DIR / "manifest.json"
IMPUTATION_RESULTS_PATH = DATA_DIR / "imputation_results.csv"

MICE_SEED_TRIALS = 10
MICE_SEEDS = list(range(1, MICE_SEED_TRIALS + 1))


# ---------------------------------------------------------------------------
# 1. Rate sensitivity
# ---------------------------------------------------------------------------

def analyse_rate_sensitivity(results_df: pd.DataFrame) -> pd.DataFrame:
    """For each (mechanism, method), returns nRMSE at each rate plus the
    delta between the lowest and highest rate, so degradation/improvement
    trends are visible directly in the table (not just the plot)."""
    pivot = (
        results_df.pivot_table(index=["mechanism", "method"], columns="rate", values="nrmse_pct")
        .reset_index()
    )
    rate_cols = sorted([c for c in pivot.columns if isinstance(c, float)])
    pivot["delta_low_to_high_rate"] = pivot[rate_cols[-1]] - pivot[rate_cols[0]]
    pivot["trend"] = pivot["delta_low_to_high_rate"].apply(
        lambda d: "improves with more missingness" if d < -0.5
        else "degrades with more missingness" if d > 0.5
        else "roughly stable"
    )
    return pivot


def plot_rate_sensitivity(results_df: pd.DataFrame, output_path: Path) -> None:
    mechanisms = sorted(results_df["mechanism"].unique())
    fig, axes = plt.subplots(1, len(mechanisms), figsize=(15, 4.5), sharey=True)

    for ax, mech in zip(axes, mechanisms):
        sub = results_df[results_df["mechanism"] == mech]
        for method in sorted(sub["method"].unique()):
            method_data = sub[sub["method"] == method].sort_values("rate")
            ax.plot(
                method_data["rate"] * 100,
                method_data["nrmse_pct"],
                marker="o",
                label=method,
            )
        ax.set_title(mech)
        ax.set_xlabel("Missingness rate (%)")
        ax.grid(alpha=0.3)

    axes[0].set_ylabel("nRMSE (%)")
    axes[-1].legend(loc="upper right", fontsize=8)
    fig.suptitle("Imputation error vs. missingness rate, by mechanism and method")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 2. Misdiagnosis cost
# ---------------------------------------------------------------------------

def analyse_misdiagnosis_cost(results_df: pd.DataFrame) -> dict:
    """Quantifies the accuracy cost of routing MCAR-diagnosed-as-Ambiguous
    data to the conservative method (median) instead of the empirically
    best MCAR method (mice), averaged across all three rates.

    This is NOT a criticism of the routing logic -- it is the honest price
    of refusing to guess between two mechanisms that are provably
    indistinguishable from observed data. The point of this analysis is to
    put a number on that price so it can be weighed against the safety
    benefit (never confidently mis-imputing a true MNAR case).
    """
    mcar = results_df[results_df["mechanism"] == "MCAR"]

    mean_by_method = mcar.groupby("method")["nrmse_pct"].mean()
    best_method = mean_by_method.idxmin()
    best_nrmse = mean_by_method.min()
    conservative_nrmse = mean_by_method["median"]

    cost_pct_points = conservative_nrmse - best_nrmse
    cost_relative_pct = (cost_pct_points / best_nrmse) * 100

    return {
        "true_mechanism_analysed": "MCAR",
        "conservative_method_used_by_router": "median",
        "conservative_method_mean_nrmse_pct": round(float(conservative_nrmse), 3),
        "best_possible_method_if_mechanism_were_known": best_method,
        "best_possible_mean_nrmse_pct": round(float(best_nrmse), 3),
        "cost_of_conservatism_pct_points": round(float(cost_pct_points), 3),
        "cost_of_conservatism_relative_pct": round(float(cost_relative_pct), 2),
        "interpretation": (
            f"Routing true-MCAR data conservatively (median, due to the diagnosis "
            f"pipeline correctly reporting it as ambiguous with MNAR) costs "
            f"{cost_pct_points:.3f} percentage points of nRMSE ({cost_relative_pct:.1f}% "
            f"relative increase) compared to the theoretical best case where the "
            f"mechanism was known for certain and MICE was used instead. This is the "
            f"quantified price of prioritising safety (never confidently mis-imputing "
            f"a true MNAR case as MCAR) over marginal accuracy."
        ),
    }


# ---------------------------------------------------------------------------
# 3. MICE seed sensitivity
# ---------------------------------------------------------------------------

def analyse_mice_seed_sensitivity(
    ground_truth: pd.DataFrame, manifest: dict
) -> tuple[pd.DataFrame, dict]:
    """Re-runs MICE with multiple random seeds on each masked file, scoring
    each run against ground truth, to measure run-to-run variability."""
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer
    from sklearn.linear_model import BayesianRidge

    rows = []

    for entry in manifest["generated_files"]:
        file_path = DATA_DIR / entry["output_file"]
        target_col = entry["target_column"]
        masked_df = pd.read_csv(file_path)
        missing_mask = masked_df[target_col].isna()

        for seed in MICE_SEEDS:
            imputer = IterativeImputer(
                estimator=BayesianRidge(), max_iter=50, tol=1e-2, random_state=seed
            )
            imputed = masked_df.copy()
            imputed[NUMERIC_COLS] = imputer.fit_transform(imputed[NUMERIC_COLS])

            scores = score_imputation(imputed, ground_truth, target_col, missing_mask)
            rows.append(
                {
                    "file": entry["output_file"],
                    "mechanism": entry["mechanism"],
                    "rate": entry["requested_rate"],
                    "seed": seed,
                    "nrmse_pct": scores["nrmse_pct"],
                }
            )

    seed_df = pd.DataFrame(rows)

    summary = (
        seed_df.groupby(["mechanism", "rate"])["nrmse_pct"]
        .agg(["mean", "std", "min", "max"])
        .reset_index()
    )
    summary["coefficient_of_variation_pct"] = (summary["std"] / summary["mean"] * 100).round(2)

    overall_cv = float(summary["coefficient_of_variation_pct"].mean())
    verdict = (
        "LOW run-to-run variability -- a single MICE run is reasonably "
        "representative for this dataset."
        if overall_cv < 5
        else "MODERATE run-to-run variability -- consider averaging multiple MICE "
        "runs for reported figures, or note this as a limitation."
        if overall_cv < 15
        else "HIGH run-to-run variability -- single-run MICE results should not be "
        "treated as stable; multiple imputation (averaging several runs) is "
        "recommended rather than relying on any one seed."
    )

    report = {
        "n_seeds_tested": MICE_SEED_TRIALS,
        "seeds": MICE_SEEDS,
        "mean_coefficient_of_variation_pct": round(overall_cv, 2),
        "verdict": verdict,
        "by_mechanism_and_rate": summary.to_dict(orient="records"),
    }

    return seed_df, report


def plot_mice_seed_sensitivity(seed_df: pd.DataFrame, output_path: Path) -> None:
    mechanisms = sorted(seed_df["mechanism"].unique())
    fig, axes = plt.subplots(1, len(mechanisms), figsize=(15, 4.5), sharey=True)

    for ax, mech in zip(axes, mechanisms):
        sub = seed_df[seed_df["mechanism"] == mech]
        rates = sorted(sub["rate"].unique())
        data_by_rate = [sub[sub["rate"] == r]["nrmse_pct"].values for r in rates]
        ax.boxplot(data_by_rate, labels=[f"{int(r*100)}%" for r in rates])
        ax.set_title(mech)
        ax.set_xlabel("Missingness rate")
        ax.grid(alpha=0.3)

    axes[0].set_ylabel("nRMSE (%) across seeds")
    fig.suptitle(f"MICE run-to-run variability across {MICE_SEED_TRIALS} random seeds")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    if not IMPUTATION_RESULTS_PATH.exists():
        raise FileNotFoundError(
            f"{IMPUTATION_RESULTS_PATH} not found. Run impute_engine.py first."
        )
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(f"{GROUND_TRUTH_PATH} not found.")
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"{MANIFEST_PATH} not found. Run synthetic_missingness.py first.")

    results_df = pd.read_csv(IMPUTATION_RESULTS_PATH)
    ground_truth = pd.read_csv(GROUND_TRUTH_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text())

    print("=== 1. Rate sensitivity ===")
    rate_table = analyse_rate_sensitivity(results_df)
    print(rate_table.round(2).to_string(index=False))
    rate_table.to_csv(DATA_DIR / "sensitivity_rate.csv", index=False)
    plot_rate_sensitivity(results_df, DATA_DIR / "sensitivity_rate.png")
    print(f"\nSaved: {DATA_DIR / 'sensitivity_rate.csv'}, {DATA_DIR / 'sensitivity_rate.png'}")

    print("\n=== 2. Misdiagnosis cost (MCAR routed conservatively) ===")
    misdiagnosis_cost = analyse_misdiagnosis_cost(results_df)
    for k, v in misdiagnosis_cost.items():
        print(f"  {k}: {v}")
    (DATA_DIR / "sensitivity_misdiagnosis_cost.json").write_text(
        json.dumps(misdiagnosis_cost, indent=2)
    )

    print(f"\n=== 3. MICE seed sensitivity ({MICE_SEED_TRIALS} seeds per file) ===")
    print("(this will take a little while -- refitting MICE many times)")
    seed_df, seed_report = analyse_mice_seed_sensitivity(ground_truth, manifest)
    print(f"\nMean coefficient of variation: {seed_report['mean_coefficient_of_variation_pct']}%")
    print(f"Verdict: {seed_report['verdict']}")
    seed_df.to_csv(DATA_DIR / "sensitivity_mice_seed.csv", index=False)
    plot_mice_seed_sensitivity(seed_df, DATA_DIR / "sensitivity_mice_seed.png")
    print(f"\nSaved: {DATA_DIR / 'sensitivity_mice_seed.csv'}, {DATA_DIR / 'sensitivity_mice_seed.png'}")

    # --- Combined report ---
    combined_report = {
        "rate_sensitivity": json.loads(rate_table.to_json(orient="records")),
        "misdiagnosis_cost": misdiagnosis_cost,
        "mice_seed_sensitivity": seed_report,
    }
    (DATA_DIR / "sensitivity_report.json").write_text(json.dumps(combined_report, indent=2))
    print(f"\nCombined report written to {DATA_DIR / 'sensitivity_report.json'}")


if __name__ == "__main__":
    main()