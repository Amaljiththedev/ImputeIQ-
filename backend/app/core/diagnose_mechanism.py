"""
diagnosis_mechanism.py

Diagnoses the likely missingness mechanism (MCAR / MAR / MNAR) of a dataset
using a three-part statistical approach, since no single test can reliably
distinguish all three mechanisms on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Precision loss occurred in moment calculation.*")

try:
    from pyampute.exploration.mcar_statistical_tests import MCARTest
except ImportError as e:
    raise ImportError(
        "pyampute is required for Little's MCAR test. Install with: "
        "pip install pyampute"
    ) from e

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
MANIFEST_PATH = DATA_DIR / "manifest.json"
REPORT_PATH = DATA_DIR / "diagnosis_report.json"

NUMERIC_COLS = ["age", "bmi", "systolic_bp", "glucose", "visits_last_year", "severity_score"]
CATEGORICAL_COLS = ["gender", "smoking_status", "region"]

ALPHA = 0.05


def run_littles_test(df: pd.DataFrame, numeric_cols: list[str]) -> float:
    """Returns the p-value from Little's MCAR test over the numeric columns.
    High p-value => fail to reject H0 => consistent with MCAR."""
    cols = [c for c in numeric_cols if c in df.columns and df[c].notna().any()]
    if len(cols) < 2:
        return 1.0
    mt = MCARTest(method="little")
    return float(mt(df[cols]))


def check_categorical_associations(
    df: pd.DataFrame, target_col: str, categorical_cols: list[str], max_categories: int = 50
) -> dict:
    """Chi-square test of independence between "target is missing" and each
    categorical column.

    FIX: high-cardinality categorical columns (e.g. CPRD lookup codes like
    medcodeid with hundreds/thousands of unique values) are bucketed rather
    than fed raw into chi2_contingency. A contingency table with mostly
    empty cells violates chi-square's expected-frequency assumptions and
    produces a statistically meaningless p-value. Rare categories are
    grouped into "__other__" first so common categories still get tested
    even on a column with a long tail of rare codes.
    """
    missing_indicator = df[target_col].isna()
    results = {}
    for col in categorical_cols:
        if col not in df.columns or col == target_col:
            continue
        series = df[col]
        n_unique = series.nunique(dropna=True)
        if n_unique < 2:
            continue

        if n_unique > max_categories:
            top_categories = series.value_counts().nlargest(max_categories - 1).index
            series = series.where(series.isin(top_categories), other="__other__")

        ct = pd.crosstab(missing_indicator, series)
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            continue
        try:
            _, p, _, _ = stats.chi2_contingency(ct)
        except ValueError:
            continue
        results[col] = float(p)
    return results


def check_numeric_associations(
    df: pd.DataFrame, target_col: str, numeric_cols: list[str]
) -> dict:
    """Welch's t-test comparing each other numeric column's values between
    rows where target_col is missing vs present. Returns {column: p_value}."""
    missing_mask = df[target_col].isna()
    results = {}
    for col in numeric_cols:
        if col not in df.columns or col == target_col:
            continue
        present_vals = df.loc[~missing_mask, col].dropna()
        missing_vals = df.loc[missing_mask, col].dropna()
        if len(present_vals) < 2 or len(missing_vals) < 2:
            continue
        _, p = stats.ttest_ind(present_vals, missing_vals, equal_var=False)
        results[col] = float(p)
    return results


def detect_structural_zero_candidate(
    df: pd.DataFrame, target_col: str, semantic_role: str | None = None
) -> dict | None:
    """Heuristic flag: is this plausibly a count/event column where missing
    means 'the event didn't happen' rather than 'unknown value'?

    FIX: now accepts an optional semantic_role and short-circuits to None
    for IDENTIFIER/CATEGORICAL columns, since a low-cardinality integer
    lookup code column can otherwise falsely match this heuristic.
    """
    if semantic_role in ("identifier", "categorical"):
        return None

    series = df[target_col].dropna()
    if series.empty:
        return None

    looks_like_count = (
        pd.api.types.is_numeric_dtype(series)
        and (series >= 0).all()
        and (series == series.round()).all()
        and series.nunique() < 10
    )
    pct_missing = df[target_col].isna().mean() * 100
    name_hints = any(
        target_col.lower().startswith(p) or p in target_col.lower()
        for p in ("n_", "num_", "count_", "events", "symptoms")
    )

    if looks_like_count and pct_missing > 30:
        return {
            "flag": "possible_structural_zero",
            "reason": (
                f"'{target_col}' looks like an event count (small integer values, "
                f"{pct_missing:.1f}% missing). High missingness in a count column "
                f"often means the event never occurred (true value = 0), not that "
                f"the value is unknown. Statistical MAR/MCAR tests cannot detect "
                f"this -- confirm with domain knowledge before trusting the "
                f"statistical diagnosis below."
            ),
            "name_pattern_match": name_hints,
        }
    return None


@dataclass
class DiagnosisResult:
    file: str
    target_col: str
    littles_p_value: float
    littles_suggests_mcar: bool
    categorical_assoc: dict = field(default_factory=dict)
    numeric_assoc: dict = field(default_factory=dict)
    significant_drivers: list = field(default_factory=list)
    diagnosis: str = ""
    actual_mechanism: str | None = None
    correct: bool | None = None
    structural_zero_warning: dict | None = None


def diagnose(
    df: pd.DataFrame,
    target_col: str,
    numeric_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    alpha: float = ALPHA,
    littles_p: float | None = None,
) -> tuple:
    if numeric_cols is None:
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if categorical_cols is None:
        categorical_cols = [c for c in df.columns if c not in numeric_cols]

    if littles_p is None:
        littles_p = run_littles_test(df, numeric_cols)
    littles_suggests_mcar = littles_p > alpha

    cat_assoc = check_categorical_associations(df, target_col, categorical_cols)
    num_assoc = check_numeric_associations(df, target_col, numeric_cols)

    # FIX: correct for multiple comparisons (Holm-Bonferroni) across all
    # candidate driver tests before flagging any as "significant". Without
    # this, testing k candidate columns at alpha=0.05 each gives an expected
    # k*0.05 false positives under true MCAR -- e.g. 10 candidates yields
    # ~0.5 expected spurious hits, misdiagnosing MCAR as MAR roughly half
    # the time. Holm controls family-wise error rate while retaining more
    # power than plain Bonferroni.
    pooled = {**cat_assoc, **num_assoc}
    if pooled:
        cols = list(pooled.keys())
        pvals = list(pooled.values())
        reject, pvals_corrected, _, _ = multipletests(pvals, alpha=alpha, method="holm")
        significant_drivers = [c for c, r in zip(cols, reject) if r]
    else:
        significant_drivers = []

    if significant_drivers:
        diagnosis = "MAR (driver(s): " + ", ".join(significant_drivers) + ")"
    elif littles_suggests_mcar:
        diagnosis = (
            f"Ambiguous: MCAR or MNAR (indistinguishable from observed data "
            f"— littles_p={littles_p:.4f})"
        )
    else:
        diagnosis = "Likely MNAR (by elimination — no observed driver found)"

    return littles_p, littles_suggests_mcar, cat_assoc, num_assoc, significant_drivers, diagnosis


def mechanism_label(diagnosis: str) -> str:
    """Collapse a diagnosis string down to MCAR / MAR / MNAR for scoring
    against the known ground-truth mechanism.

    FIX: the original checked diagnosis.startswith("MCAR"), which is DEAD
    CODE -- diagnose() never returns a string starting with the bare word
    "MCAR". The MCAR-consistent case is always phrased as
    "Ambiguous: MCAR or MNAR (...)". That branch is now checked against
    the real prefix diagnose() actually returns.
    """
    if diagnosis.startswith("MAR"):
        return "MAR"
    if diagnosis.startswith("Ambiguous"):
        return "MCAR"
    return "MNAR"


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found at {MANIFEST_PATH.resolve()}. "
            "Run synthetic_missingness.py first."
        )

    manifest = json.loads(MANIFEST_PATH.read_text())
    results: list[DiagnosisResult] = []

    for entry in manifest["generated_files"]:
        file_path = DATA_DIR / entry["output_file"]
        target_col = entry["target_column"]
        actual_mechanism = entry["mechanism"]

        df = pd.read_csv(file_path, sep=None, engine="python")
        num_cols = df.select_dtypes(include="number").columns.tolist()
        cat_cols = [c for c in df.columns if c not in num_cols]

        littles_p, littles_mcar, cat_assoc, num_assoc, drivers, diagnosis = diagnose(
            df, target_col, num_cols, cat_cols
        )

        diagnosed_mechanism = mechanism_label(diagnosis)
        correct = diagnosed_mechanism == actual_mechanism

        result = DiagnosisResult(
            file=entry["output_file"],
            target_col=target_col,
            littles_p_value=littles_p,
            littles_suggests_mcar=littles_mcar,
            categorical_assoc=cat_assoc,
            numeric_assoc=num_assoc,
            significant_drivers=drivers,
            diagnosis=diagnosis,
            actual_mechanism=actual_mechanism,
            correct=correct,
        )
        results.append(result)

        status = "OK " if correct else "FAIL"
        print(f"[{status}] {entry['output_file']:<32s} actual={actual_mechanism:<5s} "
              f"diagnosed={diagnosed_mechanism:<5s} (littles_p={littles_p:.4f})  {diagnosis}")

    n_correct = sum(1 for r in results if r.correct)
    n_total = len(results)
    print(f"\nOverall diagnosis accuracy: {n_correct}/{n_total} ({n_correct/n_total*100:.1f}%)")

    by_mechanism: dict = {}
    for r in results:
        by_mechanism.setdefault(r.actual_mechanism, []).append(r.correct)
    print("\nAccuracy by mechanism:")
    for mech, outcomes in by_mechanism.items():
        acc = sum(outcomes) / len(outcomes) * 100
        print(f"  {mech:<5s}: {sum(outcomes)}/{len(outcomes)} ({acc:.1f}%)")

    report = {
        "alpha": ALPHA,
        "n_correct": n_correct,
        "n_total": n_total,
        "accuracy_pct": round(n_correct / n_total * 100, 1),
        "accuracy_by_mechanism": {
            mech: {
                "correct": sum(outcomes),
                "total": len(outcomes),
                "pct": round(sum(outcomes) / len(outcomes) * 100, 1),
            }
            for mech, outcomes in by_mechanism.items()
        },
        "results": [
            {
                "file": r.file,
                "target_col": r.target_col,
                "actual_mechanism": r.actual_mechanism,
                "diagnosed_mechanism": mechanism_label(r.diagnosis),
                "diagnosis_detail": r.diagnosis,
                "correct": r.correct,
                "littles_p_value": round(r.littles_p_value, 6) if r.littles_p_value is not None else None,
                "littles_suggests_mcar": r.littles_suggests_mcar,
                "categorical_assoc_p_values": {k: round(v, 6) for k, v in r.categorical_assoc.items()},
                "numeric_assoc_p_values": {k: round(v, 6) for k, v in r.numeric_assoc.items()},
                "significant_drivers": r.significant_drivers,
            }
            for r in results
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()