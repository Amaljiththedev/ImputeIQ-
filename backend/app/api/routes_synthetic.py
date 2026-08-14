"""
routes_synthetic.py

API endpoints for dynamic synthetic benchmark generation, loading, and
ground-truth accuracy evaluation:
    GET  /api/synthetic/manifest             -> Returns ground truth manifest
    POST /api/synthetic/generate             -> Dynamically runs synthetic injection
    POST /api/synthetic/load/{output_file}   -> Registers synthetic CSV as active Dataset
    GET  /api/synthetic/benchmark/{dataset_id} -> Computes Ground Truth vs Diagnosis scorecard
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes import get_dataset_or_404
from app.core.diagnose_mechanism import classify_mechanism
from app.core.synthetic_missingness import (
    CARDIO_GROUND_TRUTH_PATH,
    DATA_DIR,
    MANIFEST_PATH,
    OUTPUT_DIR,
    ensure_cardio_ground_truth,
    run_cardio_pipeline,
    run_dynamic_pipeline,
)
from app.db import get_db
from app.models.db_models import Dataset, DiagnosisResult
from app.schemas.schemas import DatasetOut

router = APIRouter()


def _get_manifest_data() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        # Auto-generate if manifest doesn't exist yet
        run_cardio_pipeline()
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read synthetic manifest: {exc}")


@router.get("/manifest")
def get_synthetic_manifest() -> dict[str, Any]:
    """Returns the current synthetic missingness manifest and available benchmark datasets."""
    return _get_manifest_data()


@router.post("/generate")
def generate_synthetic_data(
    dataset_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Dynamically runs or re-runs synthetic missingness injection on any uploaded dataset
    (or base ground truth if no dataset_id passed) and returns updated manifest.
    """
    try:
        if dataset_id:
            dataset = db.get(Dataset, dataset_id)
            if not dataset:
                raise HTTPException(status_code=404, detail="Dataset not found")
            from app.jobs.runner import get_dataset_csv_path
            source_path = Path(get_dataset_csv_path(dataset))
            output_prefix = dataset.filename.rsplit(".", 1)[0]
            run_dynamic_pipeline(source_path=source_path, output_prefix=output_prefix)
        else:
            run_cardio_pipeline()
        return _get_manifest_data()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate synthetic data: {exc}")


@router.post("/load/{output_file}", response_model=DatasetOut)
def load_synthetic_dataset(
    output_file: str,
    db: Session = Depends(get_db),
) -> DatasetOut:
    """Loads a pre-generated synthetic dataset into the database as a new active Dataset
    so that users can immediately run diagnosis, imputation, and sensitivity
    analysis against known ground-truth missingness.
    """
    file_path = OUTPUT_DIR / output_file
    if not file_path.exists():
        # Try checking if it's in data dir
        file_path = DATA_DIR / output_file
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Synthetic dataset {output_file} not found.")

    try:
        df = pd.read_csv(file_path, sep=None, engine="python")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse synthetic dataset CSV: {exc}")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    dataset = Dataset(
        filename=output_file,
        storage_path=str(file_path),
        validated_storage_path=str(file_path),  # Synthetic datasets are pre-cleaned & ready for diagnosis
        row_count=len(df),
        column_names=df.columns.tolist(),
        numeric_columns=numeric_cols,
        categorical_columns=categorical_cols,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return DatasetOut.model_validate(dataset)


@router.get("/benchmark/{dataset_id}")
def get_benchmark_scorecard(
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compares the diagnosed missingness mechanism and recommended imputers against
    known ground-truth rules from manifest.json.
    """
    manifest = _get_manifest_data()
    columns_spec = manifest.get("columns", {})

    # Check dynamically if dataset matches any generated file, combined file, source file, or column specification
    gen_files = [f.get("output_file") for f in manifest.get("generated_files", [])]
    combined_file = manifest.get("combined_file")
    is_benchmark = (
        dataset.filename == combined_file
        or dataset.filename in gen_files
        or dataset.filename == manifest.get("source")
        or any(col in columns_spec for col in (dataset.column_names or []))
        or any(f.get("target_column") in (dataset.column_names or []) for f in manifest.get("generated_files", []))
    )

    diagnosis_results = db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).all()

    scorecard_items = []
    correct_count = 0
    total_evaluated = 0
    # Columns whose ground-truth mechanism cannot be recovered from observed
    # data at all (MNAR). Scoring these as hits or misses is equally wrong, so
    # they are counted separately and excluded from the accuracy denominator.
    undetectable_count = 0

    for diag in diagnosis_results:
        col = diag.target_column
        gt_info = columns_spec.get(col, {})
        gt_mech = gt_info.get("mechanism", "none").upper()
        if gt_mech == "NONE" or not gt_mech:
            # Check if this column had injection in generated_files
            for g in manifest.get("generated_files", []):
                if g.get("target_column") == col:
                    gt_mech = g.get("mechanism", "").upper()
                    gt_info = {
                        "mechanism": gt_mech,
                        "target_missing_rate": g.get("requested_rate"),
                        "actual_missing_rate": g.get("actual_missing_pct", 0) / 100.0 if g.get("actual_missing_pct") else 0,
                        "driver_column": g.get("driver_column"),
                        "rule": g.get("rule", ""),
                    }
                    break

        if gt_mech == "NONE" or not gt_mech:
            continue

        total_evaluated += 1
        diagnosed_mech = (diag.diagnosed_mechanism or "").upper()

        # Collapse the diagnosis to a single category. Substring matching was
        # the source of the previous scoring bug: the compound label
        # "AMBIGUOUS (MCAR/MNAR)" contains both "MCAR" and "MNAR", so
        # `gt_mech in diagnosed_mech` marked it an Exact Match against either
        # ground truth. A column the tool had explicitly failed to classify was
        # therefore scored as a correct answer, producing accuracies of 100%.
        # Both sides are mapped onto the same fixed set before comparison, so
        # scoring never depends on wording or spelling.
        diagnosed_cat = classify_mechanism(diagnosed_mech).value
        gt_mech = classify_mechanism(gt_mech).value

        is_match = False
        match_status = "Incorrect"

        if gt_mech == "MNAR" and diagnosed_cat == "UNRESOLVED":
            # The statistically honest outcome. MNAR depends on the unrecorded
            # values, so no procedure on observed data can confirm it. Neither
            # credited nor penalised.
            undetectable_count += 1
            match_status = "Not identifiable from observed data (expected)"
        elif gt_mech == diagnosed_cat:
            is_match = True
            correct_count += 1
            gt_driver = gt_info.get("driver_column")
            if gt_mech == "MAR" and gt_driver and gt_driver in (diag.significant_drivers or []):
                match_status = f"Exact match, driver '{gt_driver}' correctly identified"
            else:
                match_status = "Exact match"
        elif gt_mech == "MCAR" and diagnosed_cat == "UNRESOLVED":
            # Little's test can only fail to reject MCAR, never confirm it, so
            # an unresolved result is the strongest available answer here.
            is_match = True
            correct_count += 1
            match_status = "Consistent with MCAR (not rejected)"
        elif gt_mech == "MAR" and diagnosed_cat == "UNRESOLVED":
            match_status = "Missed: MAR driver not detected"
        else:
            match_status = f"Incorrect: expected {gt_mech}, diagnosed {diagnosed_cat}"

        scorecard_items.append(
            {
                "target_column": col,
                "ground_truth_mechanism": gt_mech,
                "ground_truth_driver": gt_info.get("driver_column"),
                "ground_truth_rate": gt_info.get("actual_missing_rate") or gt_info.get("target_missing_rate"),
                "ground_truth_rule": gt_info.get("rule", ""),
                "diagnosed_mechanism": diag.diagnosed_mechanism,
                "recommended_method": diag.recommended_method,
                "littles_p_value": diag.littles_p_value,
                "significant_drivers": diag.significant_drivers or [],
                "is_match": is_match,
                "match_status": match_status,
                "rationale": diag.rationale,
            }
        )

    # Accuracy is reported over the columns whose mechanism is recoverable from
    # observed data. MNAR columns are excluded from the denominator and
    # reported separately, so the headline figure is neither inflated by
    # counting non-detections as hits nor deflated by penalising the tool for a
    # limitation of the data itself.
    detectable_evaluated = total_evaluated - undetectable_count
    accuracy_pct = (
        round((correct_count / detectable_evaluated * 100.0), 1)
        if detectable_evaluated > 0
        else None
    )

    return {
        "dataset_id": dataset.id,
        "dataset_filename": dataset.filename,
        "is_benchmark_dataset": is_benchmark,
        "source_dataset": manifest.get("source", "cardio_train_ground_truth.csv"),
        "total_columns_evaluated": total_evaluated,
        "detectable_columns_evaluated": detectable_evaluated,
        "not_identifiable_columns": undetectable_count,
        "correct_mechanisms": correct_count,
        "accuracy_pct": accuracy_pct,
        "accuracy_basis": (
            f"{correct_count}/{detectable_evaluated} identifiable columns; "
            f"{undetectable_count} MNAR column(s) excluded as not identifiable "
            f"from observed data"
        ),
        "scorecard": scorecard_items,
    }
