"""
scripts/smoke_test.py

End-to-end smoke test for the ImputeIQ backend. Exercises the
full real flow over HTTP: upload -> diagnose -> poll -> impute
-> poll -> fetch results -> verify the imputed CSV has zero missing values.

Usage:
    1. Start the server:
           uvicorn app.main:app --reload
    2. In another terminal, from the backend/ directory:
           python scripts/smoke_test.py
       Or pass a CSV that already has missing values:
           python scripts/smoke_test.py data/synthetic/patient_records_mcar_10.csv
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "http://127.0.0.1:8000"
POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 60


def fail(msg: str) -> None:
    print(f"\nFAILED: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def poll_job(session: requests.Session, job_id: str, label: str) -> dict:
    """Poll GET /api/jobs/{id} until status == complete or failed."""
    start = time.time()
    status = "unknown"
    while time.time() - start < POLL_TIMEOUT_SECONDS:
        resp = session.get(f"{BASE_URL}/api/jobs/{job_id}")
        if resp.status_code != 200:
            fail(f"{label}: GET /api/jobs/{job_id} returned {resp.status_code}: {resp.text}")
        data = resp.json()
        status = data["status"]
        if status == "complete":
            return data
        if status == "failed":
            fail(f"{label}: job failed -> {data.get('error_message')}")
        time.sleep(POLL_INTERVAL_SECONDS)
    fail(f"{label}: job did not complete within {POLL_TIMEOUT_SECONDS}s (last status: {status})")


def prepare_test_file() -> Path:
    """Build a test file from the clean ground truth with missingness injected
    into two columns, so the multi-column path is exercised."""
    candidates = [
        Path(__file__).parent.parent / "app" / "data" / "patient_records_clean.csv",
        Path("app/data/patient_records_clean.csv"),
        Path("data/patient_records_clean.csv"),
    ]
    clean_path = next((p for p in candidates if p.exists()), None)
    if clean_path is None:
        fail(
            "Could not find patient_records_clean.csv. "
            "Pass a CSV with missing values as an argument:\n"
            "    python scripts/smoke_test.py path/to/file.csv"
        )

    synthetic = clean_path.parent / "synthetic" / "patient_records_mcar_10.csv"
    if synthetic.exists():
        print(f"  Using pre-generated synthetic file: {synthetic}")
        return synthetic

    df = pd.read_csv(clean_path)
    df = df.copy()
    import numpy as np

    rng = np.random.default_rng(42)
    n = len(df)
    df.loc[rng.choice(n, size=int(0.10 * n), replace=False), "systolic_bp"] = np.nan
    out = clean_path.parent / "_smoke_test_input.csv"
    df.to_csv(out, index=False)
    return out


def main() -> None:
    print(f"Target server: {BASE_URL}\n")
    session = requests.Session()

    # --- 0. Health check ---
    try:
        resp = session.get(f"{BASE_URL}/health", timeout=5)
    except requests.exceptions.ConnectionError:
        fail(
            "Could not connect to the server. Is it running?\n"
            "  docker compose up   OR   uvicorn app.main:app --reload"
        )
    if resp.status_code != 200 or resp.json().get("status") != "ok":
        fail(f"/health returned unexpected response: {resp.status_code} {resp.text}")
    ok("Server is up (/health)")

    # --- 1. Prepare input file ---
    if len(sys.argv) > 1:
        test_file = Path(sys.argv[1])
        if not test_file.exists():
            fail(f"Given file does not exist: {test_file}")
    else:
        test_file = prepare_test_file()
        ok(f"Test file: {test_file}")

    original_df = pd.read_csv(test_file)
    original_missing_cols = original_df.columns[original_df.isna().any()].tolist()
    if not original_missing_cols:
        fail(f"{test_file} has no missing values -- nothing to diagnose/impute.")
    ok(f"Input: {len(original_df)} rows, missing in: {original_missing_cols}")

    # --- 2. Upload ---
    with open(test_file, "rb") as f:
        resp = session.post(
            f"{BASE_URL}/api/datasets/upload",
            files={"file": (test_file.name, f, "text/csv")},
        )
    if resp.status_code != 200:
        fail(f"Upload failed ({resp.status_code}): {resp.text}")
    dataset = resp.json()
    dataset_id = dataset["id"]
    ok(
        f"Uploaded dataset {dataset_id} ({dataset['row_count']} rows, "
        f"{len(dataset['column_names'])} columns)"
    )

    # --- 3. Diagnose ---
    resp = session.post(f"{BASE_URL}/api/datasets/{dataset_id}/diagnose")
    if resp.status_code != 200:
        fail(f"Starting diagnosis failed ({resp.status_code}): {resp.text}")
    diag_job_id = resp.json()["id"]
    ok(f"Diagnosis job started: {diag_job_id}")

    diag_data = poll_job(session, diag_job_id, "diagnose")
    ok("Diagnosis job complete")

    diag_results = diag_data.get("results", [])
    diagnosed_cols = {r["target_column"] for r in diag_results}
    ok(f"Diagnosed columns: {sorted(diagnosed_cols)}")
    for r in diag_results:
        print(
            f"    - {r['target_column']}: {r['diagnosed_mechanism']} "
            f"(n_missing={r['n_missing']}, drivers={r['significant_drivers']})"
        )

    # --- 4. Impute ---
    resp = session.post(f"{BASE_URL}/api/datasets/{dataset_id}/impute")
    if resp.status_code != 200:
        fail(f"Starting imputation failed ({resp.status_code}): {resp.text}")
    impute_job_id = resp.json()["id"]
    ok(f"Imputation job started: {impute_job_id}")

    poll_job(session, impute_job_id, "impute")
    ok("Imputation job complete")

    # --- 5. Fetch full results ---
    resp = session.get(f"{BASE_URL}/api/datasets/{dataset_id}/results")
    if resp.status_code != 200:
        fail(f"Fetching results failed ({resp.status_code}): {resp.text}")
    full_results = resp.json()

    imp_results = full_results["imputation_results"]
    for r in imp_results:
        flag = " [LOW CONFIDENCE]" if r["low_confidence"] else ""
        print(
            f"    - {r['target_column']}: method={r['method_used']}{flag} "
            f"(n_imputed={r['n_imputed']})"
        )

    ok(
        f"Results endpoint returned {len(full_results['diagnosis_results'])} diagnosis + "
        f"{len(imp_results)} imputation records"
    )

    # --- 6. Download imputed CSV and verify zero missing ---
    resp = session.get(f"{BASE_URL}/api/datasets/{dataset_id}/download")
    if resp.status_code != 200:
        fail(f"Download failed ({resp.status_code}): {resp.text}")

    import io

    imputed_df = pd.read_csv(io.BytesIO(resp.content))
    remaining_missing = int(imputed_df.isna().sum().sum())
    if remaining_missing != 0:
        fail(f"Imputed CSV still has {remaining_missing} missing values!")
    if imputed_df.shape != original_df.shape:
        fail(f"Shape mismatch: imputed {imputed_df.shape} vs original {original_df.shape}")
    ok(f"Imputed CSV verified: shape={imputed_df.shape}, missing={remaining_missing}")

    print("\nAll checks passed. The pipeline is working end-to-end.")


if __name__ == "__main__":
    main()
