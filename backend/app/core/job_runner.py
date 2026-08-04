"""
job_runner.py

Executes diagnosis and imputation processes asynchronously via FastAPI background tasks.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

import os
from app.db import SessionLocal
from app.models.db_models import Job, Dataset, JobStatus, DiagnosisResult, ImputationResult
from app.core.diagnose_mechanism import diagnose, detect_structural_zero_candidate
from app.core.method_router import route, apply_routed_imputation
from app.core.column_semantics import get_columns_by_role, SemanticRole, classify_dataset_semantics


def get_dataset_csv_path(dataset: Dataset) -> str:
    """Returns validated_storage_path if present and exists on disk, otherwise original storage_path."""
    val_path = getattr(dataset, "validated_storage_path", None)
    if val_path and os.path.exists(val_path):
        return val_path
    return dataset.storage_path


def _diagnose_one_column(
    df: pd.DataFrame,
    col: str,
    col_role: str,
    numeric_cols: list[str],
    categorical_cols: list[str],
    job_id: str,
    dataset_id: str,
) -> DiagnosisResult | None:
    """
    Diagnoses a single column and returns a DiagnosisResult row (not yet
    committed). Isolated into its own function so a single bad column
    (e.g. a high-cardinality identifier that breaks a chi-square/Little's
    test) can be caught and skipped without crashing the entire job and
    losing every other column's already-computed diagnosis.

    IDENTIFIER columns skip the expensive/risky mechanism diagnosis
    entirely (Little's test, chi-square associations) since the routing
    decision for identifiers is role-based, not mechanism-based -- running
    statistical tests on a near-unique ID column is both wasted work and a
    likely source of crashes (e.g. chi-square blowing up on hundreds of
    unique categories).
    """
    n_missing = int(df[col].isna().sum())
    if n_missing == 0:
        return None

    from app.core.method_router import route
    available_display_methods = ["Median", "Mean", "KNN", "MICE", "Regression", "Zero", "Mode", "Flag-Only"]
    method_display_map = {
        "mice": "MICE",
        "median": "Median",
        "mean": "Mean",
        "knn": "KNN",
        "regression": "Regression",
        "zero": "Zero",
        "mode": "Mode",
        "flag_only": "Flag-Only",
    }

    if col_role == SemanticRole.IDENTIFIER.value:
        decision = route("Identifier (key/ID)", structural_zero_warning=None, semantic_role=col_role)
        rec_display = method_display_map.get(decision.method.lower(), decision.method.capitalize())
        return DiagnosisResult(
            job_id=job_id,
            dataset_id=dataset_id,
            target_column=col,
            diagnosed_mechanism="Identifier (key/ID)",
            diagnosis_detail=(
                "Column is a unique identifier/key; missingness mechanism "
                "diagnosis skipped since imputation is never statistically "
                "performed on identifier columns regardless of mechanism."
            ),
            littles_p_value=None,
            littles_suggests_mcar=False,
            categorical_assoc_p_values={},
            numeric_assoc_p_values={},
            significant_drivers=[],
            n_missing=n_missing,
            recommended_method=rec_display,
            rationale=decision.rationale,
            available_methods=available_display_methods,
            is_cautious_default=decision.low_confidence,
            structural_zero_warning=None,
            semantic_role=col_role,
        )

    littles_p, littles_mcar, cat_assoc, num_assoc, drivers, diagnosis = diagnose(
        df, col, numeric_cols, categorical_cols
    )

    structural_zero = detect_structural_zero_candidate(df, col)

    if diagnosis.startswith("MAR"):
        diag_mech = "MAR"
    elif diagnosis.startswith("Ambiguous"):
        diag_mech = "Ambiguous (MCAR/MNAR)"
    else:
        diag_mech = diagnosis

    decision = route(diag_mech, structural_zero_warning=structural_zero, semantic_role=col_role)
    rec_display = method_display_map.get(decision.method.lower(), decision.method.capitalize())

    return DiagnosisResult(
        job_id=job_id,
        dataset_id=dataset_id,
        target_column=col,
        diagnosed_mechanism=diag_mech,
        diagnosis_detail=diagnosis,
        littles_p_value=littles_p,
        littles_suggests_mcar=littles_mcar,
        categorical_assoc_p_values=cat_assoc,
        numeric_assoc_p_values=num_assoc,
        significant_drivers=drivers,
        n_missing=n_missing,
        recommended_method=rec_display,
        rationale=decision.rationale,
        available_methods=available_display_methods,
        is_cautious_default=decision.low_confidence,
        structural_zero_warning=structural_zero,
        semantic_role=col_role,
    )


def run_diagnosis_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        dataset = db.query(Dataset).filter(Dataset.id == job.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {job.dataset_id} not found.")

        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")
        roles_map = classify_dataset_semantics(df)
        roles = get_columns_by_role(df)
        numeric_cols = roles[SemanticRole.CONTINUOUS]
        categorical_cols = roles[SemanticRole.CATEGORICAL]

        db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).delete()
        db.commit()

        failed_columns: list[str] = []

        for col in df.columns:
            col_role = roles_map[col].role.value if col in roles_map else "continuous"
            if col_role == "continuous" and col not in numeric_cols:
                numeric_cols.append(col)

            try:
                diag_res = _diagnose_one_column(
                    df, col, col_role, numeric_cols, categorical_cols, job.id, dataset.id
                )
            except Exception:
                # One bad column (e.g. malformed data, pathological cardinality)
                # must not take down diagnosis for every other column.
                failed_columns.append(col)
                continue

            if diag_res is not None:
                db.add(diag_res)

        job.status = JobStatus.COMPLETE
        job.completed_at = datetime.now(timezone.utc)
        if failed_columns:
            job.error_message = (
                f"Diagnosis completed with {len(failed_columns)} column(s) "
                f"skipped due to errors: {', '.join(failed_columns)}"
            )
        db.commit()

    except Exception as e:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = f"{str(e)}\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()


def run_imputation_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        dataset = db.query(Dataset).filter(Dataset.id == job.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {job.dataset_id} not found.")

        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")
        roles = get_columns_by_role(df)
        numeric_cols = roles[SemanticRole.CONTINUOUS]
        categorical_cols = roles[SemanticRole.CATEGORICAL]

        diag_results = db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).all()

        if not diag_results:
            roles_map = classify_dataset_semantics(df)
            for col in df.columns:
                col_role = roles_map[col].role.value if col in roles_map else "continuous"
                if col_role == "continuous" and col not in numeric_cols:
                    numeric_cols.append(col)

                try:
                    diag_res = _diagnose_one_column(
                        df, col, col_role, numeric_cols, categorical_cols, job.id, dataset.id
                    )
                except Exception:
                    continue

                if diag_res is not None:
                    db.add(diag_res)
            db.commit()
            diag_results = db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).all()

        imputed_df = df.copy()

        db.query(ImputationResult).filter(ImputationResult.dataset_id == dataset.id).delete()

        results_dir = Path(__file__).resolve().parent.parent / "data" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        imputed_file_path = results_dir / f"{dataset.id}_imputed.csv"

        failed_columns: list[str] = []

        for diag in diag_results:
            col = diag.target_column
            try:
                decision = route(
                    diag.diagnosed_mechanism,
                    structural_zero_warning=diag.structural_zero_warning,
                    semantic_role=diag.semantic_role,
                )
                temp_imputed_df, _ = apply_routed_imputation(
                    imputed_df,
                    col,
                    numeric_cols,
                    diag.diagnosis_detail,
                    structural_zero_warning=diag.structural_zero_warning,
                    semantic_role=diag.semantic_role,
                )
            except Exception:
                # A single column's imputation failure (e.g. an unregistered
                # method name, or a degenerate all-NaN column) must not
                # discard imputation results already computed for every
                # other column in this dataset.
                failed_columns.append(col)
                continue

            imputed_df[col] = temp_imputed_df[col]
            flag_col = f"{col}_missing"
            if flag_col in temp_imputed_df:
                imputed_df[flag_col] = temp_imputed_df[flag_col]

            imp_res = ImputationResult(
                job_id=job.id,
                dataset_id=dataset.id,
                target_column=col,
                routed_mechanism=decision.mechanism,
                method_used=decision.method,
                low_confidence=decision.low_confidence,
                rationale=decision.rationale,
                n_imputed=diag.n_missing,
                imputed_file_path=str(imputed_file_path),
                semantic_role=diag.semantic_role,
            )
            db.add(imp_res)

        imputed_df.to_csv(imputed_file_path, index=False)

        job.status = JobStatus.COMPLETE
        job.completed_at = datetime.now(timezone.utc)
        if failed_columns:
            job.error_message = (
                f"Imputation completed with {len(failed_columns)} column(s) "
                f"skipped due to errors: {', '.join(failed_columns)}"
            )
        db.commit()

    except Exception as e:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = f"{str(e)}\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()