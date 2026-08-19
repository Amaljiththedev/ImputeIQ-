"""
app/jobs/runner.py

Background job functions run via FastAPI's BackgroundTasks. Each function
opens its own DB session (BackgroundTasks run after the request's own
session has already closed, so a fresh session is required here), updates
the Job row's status as it progresses, and writes results into
DiagnosisResult / ImputationResult rows.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.diagnose_mechanism import CATEGORICAL_COLS, NUMERIC_COLS
from app.core.llm_explainer import generate_explanation
from app.core.pipeline import diagnose_all_columns, impute_all_columns, impute_all_columns_with_overrides
from app.db import SessionLocal
from app.models.db_models import (
    Dataset,
    DiagnosisResult,
    ExplanationResultRow,
    ImputationResult,
    Job,
    JobStatus,
)
from app.socket_manager import emit_to_job

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("data/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _now():
    return datetime.now(timezone.utc)


def get_dataset_csv_path(dataset: Dataset) -> str:
    """Returns validated_storage_path if present and exists on disk, otherwise original storage_path.
    Ensures downstream diagnosis and imputation run cleanly on the preprocessed copy (`validated_df`)
    while leaving the original uploaded file (`storage_path`) untouched.
    """
    import os
    val_path = getattr(dataset, "validated_storage_path", None)
    if val_path and os.path.exists(val_path):
        return val_path
    return dataset.storage_path


def sanitize_for_json(val):
    """Sanitizes floats, dictionaries, lists, and objects before database insertion so NaN/Infinity
    are converted to None/null to prevent PostgreSQL (psycopg2.errors.InvalidTextRepresentation) JSON syntax errors.
    """
    import math
    if val is None:
        return None
    if isinstance(val, float) or (hasattr(val, "dtype") and pd.api.types.is_float_dtype(val)):
        try:
            if math.isnan(val) or math.isinf(val):
                return None
            return float(val)
        except (TypeError, ValueError):
            return None
    if isinstance(val, dict):
        return {k: sanitize_for_json(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [sanitize_for_json(v) for v in val]
    return val


def get_dataset_columns(dataset: Dataset, df: pd.DataFrame) -> tuple[list[str], list[str]]:
    from app.core.column_semantics import get_columns_by_role, SemanticRole
    roles = get_columns_by_role(df)
    return roles[SemanticRole.CONTINUOUS], roles[SemanticRole.CATEGORICAL]


def run_diagnosis_job(job_id: str) -> None:
    """Background task: loads the dataset's CSV, runs diagnose_all_columns,
    writes one DiagnosisResult row per missing column, updates Job status.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = _now()
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)
        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")

        numeric_cols, categorical_cols = get_dataset_columns(dataset, df)

        available_display_methods = ["PMM", "MICE", "Median", "Mean", "KNN", "Regression", "Zero", "Mode", "Flag-Only"]
        method_display_map = {
            "pmm": "PMM",
            "mice": "MICE",
            "median": "Median",
            "mean": "Mean",
            "knn": "KNN",
            "regression": "Regression",
            "zero": "Zero",
            "mode": "Mode",
            "flag_only": "Flag-Only",
        }
        from app.core.method_router import route

        diagnoses = diagnose_all_columns(df, numeric_cols, categorical_cols)

        for d in diagnoses:
            decision = route(d.diagnosed_mechanism, structural_zero_warning=d.structural_zero_warning, semantic_role=d.semantic_role)
            rec_display = method_display_map.get(decision.method.lower(), decision.method.capitalize())

            db.add(
                DiagnosisResult(
                    job_id=job.id,
                    dataset_id=dataset.id,
                    target_column=d.target_column,
                    diagnosed_mechanism=d.diagnosed_mechanism,
                    diagnosis_detail=d.diagnosis_detail,
                    littles_p_value=sanitize_for_json(d.littles_p_value),
                    littles_suggests_mcar=d.littles_suggests_mcar,
                    categorical_assoc_p_values=sanitize_for_json(d.categorical_assoc_p_values),
                    numeric_assoc_p_values=sanitize_for_json(d.numeric_assoc_p_values),
                    significant_drivers=sanitize_for_json(d.significant_drivers),
                    n_missing=d.n_missing,
                    recommended_method=rec_display,
                    rationale=decision.rationale,
                    available_methods=available_display_methods,
                    is_cautious_default=decision.low_confidence,
                    structural_zero_warning=sanitize_for_json(d.structural_zero_warning),
                    semantic_role=d.semantic_role,
                )
            )

        job.status = JobStatus.COMPLETE
        job.completed_at = _now()
        db.commit()

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = f"{exc}\n{traceback.format_exc()}"
            job.completed_at = _now()
            db.commit()
    finally:
        db.close()


def run_imputation_job(job_id: str) -> None:
    """Background task: re-runs diagnosis, applies routed imputation,
    saves the imputed CSV, writes one ImputationResult row per column,
    updates Job status.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = _now()
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)
        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")

        numeric_cols, categorical_cols = get_dataset_columns(dataset, df)

        diagnoses = diagnose_all_columns(df, numeric_cols, categorical_cols)
        imputed_df, imputations = impute_all_columns(df, numeric_cols, diagnoses)

        output_path = RESULTS_DIR / f"{dataset.id}_imputed_{job.id}.csv"
        imputed_df.to_csv(output_path, index=False)

        for imp in imputations:
            db.add(
                ImputationResult(
                    job_id=job.id,
                    dataset_id=dataset.id,
                    target_column=imp.target_column,
                    routed_mechanism=imp.routed_mechanism,
                    method_used=imp.method_used,
                    low_confidence=imp.low_confidence,
                    rationale=imp.rationale,
                    n_imputed=imp.n_imputed,
                    n_unimputable=getattr(imp, "n_unimputable", 0),
                    unimputable_reason=getattr(imp, "unimputable_reason", None),
                    imputed_file_path=str(output_path),
                    semantic_role=imp.semantic_role,
                )
            )

        job.status = JobStatus.COMPLETE
        job.completed_at = _now()
        db.commit()

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = f"{exc}\n{traceback.format_exc()}"
            job.completed_at = _now()
            db.commit()
    finally:
        db.close()


def run_explanation_job(job_id: str) -> None:
    """Background task: reads latest results, calls LLM explainer,
    writes an ExplanationResultRow.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = _now()
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)

        diagnosis_rows = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.dataset_id == dataset.id)
            .order_by(DiagnosisResult.created_at.desc())
            .all()
        )
        imputation_rows = (
            db.query(ImputationResult)
            .filter(ImputationResult.dataset_id == dataset.id)
            .order_by(ImputationResult.created_at.desc())
            .all()
        )

        latest_diagnosis_by_col = {}
        for row in diagnosis_rows:
            latest_diagnosis_by_col.setdefault(row.target_column, row)

        latest_imputation_by_col = {}
        for row in imputation_rows:
            latest_imputation_by_col.setdefault(row.target_column, row)

        column_reports = []
        for col, d in latest_diagnosis_by_col.items():
            imp = latest_imputation_by_col.get(col)
            column_reports.append(
                {
                    "target_column": col,
                    "diagnosed_mechanism": d.diagnosed_mechanism,
                    "diagnosis_detail": d.diagnosis_detail,
                    "n_missing": d.n_missing,
                    # Lets the prompt state the missing proportion instead of
                    # asking the model to infer one it has no denominator for.
                    "row_count": dataset.row_count,
                    "method_used": imp.method_used if imp else "N/A",
                    "low_confidence": imp.low_confidence if imp else True,
                    "rationale": imp.rationale if imp else "Not yet imputed.",
                }
            )

        result = generate_explanation(column_reports)

        db.add(
            ExplanationResultRow(
                job_id=job.id,
                dataset_id=dataset.id,
                generated_by=result.generated_by,
                overall_summary=result.explanation.overall_summary,
                columns_json=[
                    {"target_column": report["target_column"], **col.model_dump()}
                    for report, col in zip(column_reports, result.explanation.columns)
                ],
            )
        )

        job.status = JobStatus.COMPLETE
        job.completed_at = _now()
        db.commit()

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = f"{exc}\n{traceback.format_exc()}"
            job.completed_at = _now()
            db.commit()
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Unified pipeline — runs diagnose → impute → explain in a single
# background task, pushing real-time updates via Socket.IO.
# ---------------------------------------------------------------------------


def run_full_pipeline(job_id: str) -> None:  # noqa: C901
    """Unified background task that runs all three processing stages
    sequentially and emits Socket.IO events at each transition.

    Events emitted (room = ``job:{job_id}``):
        job:phase   — ``{ phase, message }``  when the active phase changes
        job:log     — ``{ message }``         for granular progress messages
        job:complete — ``{}``                  when all stages finish
        job:error   — ``{ message }``         if any stage fails
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = _now()
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)
        dataset_id = dataset.id

        # ── Phase 1: Diagnose ──────────────────────────────────────────
        emit_to_job(job_id, "job:phase", {"phase": "diagnosing", "message": "Starting missingness diagnosis…"})

        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")
        emit_to_job(job_id, "job:log", {"message": f"Loaded {len(df)} rows × {len(df.columns)} columns"})

        numeric_cols, categorical_cols = get_dataset_columns(dataset, df)

        diagnoses = diagnose_all_columns(df, numeric_cols, categorical_cols)
        emit_to_job(job_id, "job:log", {"message": f"Diagnosed {len(diagnoses)} columns with missing data"})

        available_display_methods = ["PMM", "MICE", "Median", "Mean", "KNN", "Regression", "Zero", "Mode", "Flag-Only"]
        method_display_map = {
            "pmm": "PMM",
            "mice": "MICE",
            "median": "Median",
            "mean": "Mean",
            "knn": "KNN",
            "regression": "Regression",
            "zero": "Zero",
            "mode": "Mode",
            "flag_only": "Flag-Only",
        }
        from app.core.method_router import route

        for d in diagnoses:
            decision = route(d.diagnosed_mechanism, structural_zero_warning=d.structural_zero_warning, semantic_role=d.semantic_role)
            rec_display = method_display_map.get(decision.method.lower(), decision.method.capitalize())
            db.add(
                DiagnosisResult(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    target_column=d.target_column,
                    diagnosed_mechanism=d.diagnosed_mechanism,
                    diagnosis_detail=d.diagnosis_detail,
                    littles_p_value=sanitize_for_json(d.littles_p_value),
                    littles_suggests_mcar=d.littles_suggests_mcar,
                    categorical_assoc_p_values=sanitize_for_json(d.categorical_assoc_p_values),
                    numeric_assoc_p_values=sanitize_for_json(d.numeric_assoc_p_values),
                    significant_drivers=sanitize_for_json(d.significant_drivers),
                    n_missing=d.n_missing,
                    recommended_method=rec_display,
                    rationale=decision.rationale,
                    available_methods=available_display_methods,
                    is_cautious_default=decision.low_confidence,
                    structural_zero_warning=sanitize_for_json(d.structural_zero_warning),
                    semantic_role=d.semantic_role,
                )
            )
            db.commit()
        emit_to_job(job_id, "job:log", {"message": "Diagnosis results saved"})

        # ── Phase 2: Impute ────────────────────────────────────────────
        emit_to_job(job_id, "job:phase", {"phase": "imputing", "message": "Applying imputation strategies…"})

        imputed_df, imputations = impute_all_columns(df, numeric_cols, diagnoses)

        output_path = RESULTS_DIR / f"{dataset_id}_imputed_{job.id}.csv"
        imputed_df.to_csv(output_path, index=False)
        emit_to_job(job_id, "job:log", {"message": f"Imputed {len(imputations)} columns, saved to {output_path.name}"})

        for imp in imputations:
            db.add(
                ImputationResult(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    target_column=imp.target_column,
                    routed_mechanism=imp.routed_mechanism,
                    method_used=imp.method_used,
                    low_confidence=imp.low_confidence,
                    rationale=imp.rationale,
                    n_imputed=imp.n_imputed,
                    n_unimputable=getattr(imp, "n_unimputable", 0),
                    unimputable_reason=getattr(imp, "unimputable_reason", None),
                    imputed_file_path=str(output_path),
                    semantic_role=imp.semantic_role,
                )
            )
        db.commit()
        emit_to_job(job_id, "job:log", {"message": "Imputation results saved"})

        # ── Phase 3: Explain (LLM) ────────────────────────────────────
        emit_to_job(job_id, "job:phase", {"phase": "explaining", "message": "Generating plain-language explanation…"})

        # Build column reports from the data we just created (no extra DB query needed)
        column_reports = []
        for diag, imp in zip(diagnoses, imputations):
            column_reports.append(
                {
                    "target_column": diag.target_column,
                    "diagnosed_mechanism": diag.diagnosed_mechanism,
                    "diagnosis_detail": diag.diagnosis_detail,
                    "n_missing": diag.n_missing,
                    "row_count": dataset.row_count,
                    "method_used": imp.method_used,
                    "low_confidence": imp.low_confidence,
                    "rationale": imp.rationale,
                }
            )

        try:
            emit_to_job(job_id, "job:log", {"message": "Generating plain-language explanation…"})
            result = generate_explanation(column_reports)

            exp_map = {col.target_column: col for col in result.explanation.columns}
            columns_json = []
            for i, report in enumerate(column_reports):
                col_name = report["target_column"]
                col_exp = exp_map.get(col_name) or (result.explanation.columns[i] if i < len(result.explanation.columns) else None)
                if col_exp:
                    col_dict = col_exp.model_dump()
                    col_dict["target_column"] = col_name
                    columns_json.append(col_dict)
                else:
                    columns_json.append({
                        "target_column": col_name,
                        "plain_language_summary": f"Diagnosed with {report['diagnosed_mechanism']} ({report['n_missing']} missing values).",
                        "what_this_means_for_the_data": report["diagnosis_detail"],
                        "imputation_explanation": f"Imputed using {report.get('method_used', 'standard method')}: {report.get('rationale', '')}",
                        "confidence_note": "Standard confidence assessment based on sample properties." if not report.get('low_confidence') else "Low confidence due to sample characteristics or high missingness.",
                        "recommended_action": "Verify imputed distribution against domain expectations and check for any remaining outliers."
                    })

            db.add(
                ExplanationResultRow(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    generated_by=result.generated_by,
                    overall_summary=result.explanation.overall_summary,
                    columns_json=columns_json,
                )
            )
            db.commit()
            emit_to_job(job_id, "job:log", {"message": "Explanation generated and saved successfully"})
        except Exception as explain_exc:
            logger.warning("Explanation generation failed (%s), saving analytical fallback to database.", explain_exc)
            from app.core.llm_explainer import _generate_fallback_explanation
            fb_result = _generate_fallback_explanation(column_reports)
            db.add(
                ExplanationResultRow(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    generated_by=fb_result.generated_by,
                    overall_summary=fb_result.explanation.overall_summary,
                    columns_json=[col.model_dump() for col in fb_result.explanation.columns],
                )
            )
            db.commit()
            emit_to_job(job_id, "job:log", {"message": "Analytical fallback explanation generated and saved successfully"})

        # ── Done ───────────────────────────────────────────────────────
        job.status = JobStatus.COMPLETE
        job.completed_at = _now()
        db.commit()

        emit_to_job(job_id, "job:phase", {"phase": "complete", "message": "All processing complete"})
        emit_to_job(job_id, "job:complete", {"dataset_id": dataset_id})

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        error_msg = f"{exc}\n{traceback.format_exc()}"
        logger.error("Pipeline failed for job %s: %s", job_id, error_msg)

        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = error_msg
            job.completed_at = _now()
            db.commit()

        emit_to_job(job_id, "job:error", {"message": str(exc)})
    finally:
        db.close()


def run_recommendation_job(job_id: str) -> None:
    """Runs Phase 1 (Diagnosis) + Recommendation determining what imputation method to recommend,
    saves the DiagnosisResult entries with recommendation metadata, and pauses at AWAITING_APPROVAL.
    """
    from app.core.method_router import route

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = _now()
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)
        dataset_id = dataset.id

        emit_to_job(job_id, "job:phase", {"phase": "diagnosing", "message": "Starting missingness diagnosis & recommendation generation…"})

        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")
        numeric_cols, categorical_cols = get_dataset_columns(dataset, df)

        diagnoses = diagnose_all_columns(df, numeric_cols, categorical_cols)
        emit_to_job(job_id, "job:log", {"message": f"Diagnosed {len(diagnoses)} columns with missing data"})

        if len(diagnoses) == 0:
            job.status = JobStatus.COMPLETE
            job.completed_at = _now()
            db.commit()
            emit_to_job(job_id, "job:log", {"message": "No missing values detected across dataset numeric columns."})
            emit_to_job(job_id, "job:complete", {})
            return

        available_display_methods = ["PMM", "MICE", "Median", "Mean", "KNN", "Regression", "Zero", "Mode", "Flag-Only"]
        method_display_map = {
            "pmm": "PMM",
            "mice": "MICE",
            "median": "Median",
            "mean": "Mean",
            "knn": "KNN",
            "regression": "Regression",
            "zero": "Zero",
            "mode": "Mode",
            "flag_only": "Flag-Only",
        }

        for d in diagnoses:
            decision = route(d.diagnosed_mechanism, structural_zero_warning=d.structural_zero_warning, semantic_role=d.semantic_role)
            rec_display = method_display_map.get(decision.method.lower(), decision.method.capitalize())

            db.add(
                DiagnosisResult(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    target_column=d.target_column,
                    diagnosed_mechanism=d.diagnosed_mechanism,
                    diagnosis_detail=d.diagnosis_detail,
                    littles_p_value=sanitize_for_json(d.littles_p_value),
                    littles_suggests_mcar=d.littles_suggests_mcar,
                    categorical_assoc_p_values=sanitize_for_json(d.categorical_assoc_p_values),
                    numeric_assoc_p_values=sanitize_for_json(d.numeric_assoc_p_values),
                    significant_drivers=sanitize_for_json(d.significant_drivers),
                    n_missing=d.n_missing,
                    recommended_method=rec_display,
                    rationale=decision.rationale,
                    available_methods=available_display_methods,
                    is_cautious_default=decision.low_confidence,
                    structural_zero_warning=sanitize_for_json(d.structural_zero_warning),
                    semantic_role=d.semantic_role,
                )
            )
            db.commit()

        job.status = JobStatus.AWAITING_APPROVAL
        db.commit()

        emit_to_job(job_id, "job:log", {"message": "Recommendations generated. Awaiting human-in-the-loop approval."})
        emit_to_job(job_id, "job:phase", {"phase": "awaiting_approval", "message": "Please review and approve the recommended imputation methods."})

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        error_msg = f"{exc}\n{traceback.format_exc()}"
        logger.error("Recommendation job failed for job %s: %s", job_id, error_msg)

        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = error_msg
            job.completed_at = _now()
            db.commit()

        emit_to_job(job_id, "job:error", {"message": str(exc)})
    finally:
        db.close()


def run_approved_imputation_and_explanation_job(job_id: str, method_overrides: dict[str, str]) -> None:
    """Runs Phase 2 (Impute) using the user-approved/overridden methods per column,
    then executes Phase 3 (Explain) and marks the job COMPLETE.
    """
    from app.core.pipeline import ColumnDiagnosis

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        db.commit()

        dataset = db.get(Dataset, job.dataset_id)
        dataset_id = dataset.id

        # Load diagnosis results for this dataset / job
        diag_rows = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.dataset_id == dataset_id)
            .order_by(DiagnosisResult.created_at.desc())
            .all()
        )
        seen_cols = set()
        diagnoses = []
        for r in diag_rows:
            if r.target_column not in seen_cols:
                seen_cols.add(r.target_column)
                diagnoses.append(
                    ColumnDiagnosis(
                        target_column=r.target_column,
                        diagnosed_mechanism=r.diagnosed_mechanism,
                        diagnosis_detail=r.diagnosis_detail,
                        littles_p_value=r.littles_p_value,
                        littles_suggests_mcar=r.littles_suggests_mcar,
                        categorical_assoc_p_values=r.categorical_assoc_p_values,
                        numeric_assoc_p_values=r.numeric_assoc_p_values,
                        significant_drivers=r.significant_drivers,
                        n_missing=r.n_missing,
                        structural_zero_warning=r.structural_zero_warning,
                        semantic_role=r.semantic_role,
                    )
                )

        emit_to_job(job_id, "job:phase", {"phase": "imputing", "message": "Applying approved imputation strategies…"})

        df = pd.read_csv(get_dataset_csv_path(dataset), sep=None, engine="python")
        numeric_cols, _ = get_dataset_columns(dataset, df)

        imputed_df, imputations = impute_all_columns_with_overrides(df, numeric_cols, diagnoses, method_overrides)

        output_path = RESULTS_DIR / f"{dataset_id}_imputed_{job.id}.csv"
        imputed_df.to_csv(output_path, index=False)
        emit_to_job(job_id, "job:log", {"message": f"Imputed {len(imputations)} columns with approved methods, saved to {output_path.name}"})

        for imp in imputations:
            db.add(
                ImputationResult(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    target_column=imp.target_column,
                    routed_mechanism=imp.routed_mechanism,
                    method_used=imp.method_used,
                    low_confidence=imp.low_confidence,
                    rationale=imp.rationale,
                    n_imputed=imp.n_imputed,
                    n_unimputable=getattr(imp, "n_unimputable", 0),
                    unimputable_reason=getattr(imp, "unimputable_reason", None),
                    imputed_file_path=str(output_path),
                    semantic_role=imp.semantic_role,
                )
            )
            db.commit()

        # ── Phase 3: Explain ───────────────────────────────────────────
        emit_to_job(job_id, "job:phase", {"phase": "explaining", "message": "Generating plain-language explanation of approved pipeline…"})

        column_reports = [
            {
                "target_column": diag.target_column,
                "diagnosed_mechanism": diag.diagnosed_mechanism,
                "diagnosis_detail": diag.diagnosis_detail,
                "n_missing": diag.n_missing,
                "row_count": dataset.row_count,
                "method_used": imp.method_used,
                "low_confidence": imp.low_confidence,
                "rationale": imp.rationale,
            }
            for diag, imp in zip(diagnoses, imputations)
        ]

        try:
            emit_to_job(job_id, "job:log", {"message": "Generating plain-language explanation…"})
            result = generate_explanation(column_reports)

            exp_map = {col.target_column: col for col in result.explanation.columns}
            columns_json = []
            for i, report in enumerate(column_reports):
                col_name = report["target_column"]
                col_exp = exp_map.get(col_name) or (result.explanation.columns[i] if i < len(result.explanation.columns) else None)
                if col_exp:
                    col_dict = col_exp.model_dump()
                    col_dict["target_column"] = col_name
                    columns_json.append(col_dict)
                else:
                    columns_json.append({
                        "target_column": col_name,
                        "plain_language_summary": f"Diagnosed with {report['diagnosed_mechanism']} ({report['n_missing']} missing values).",
                        "what_this_means_for_the_data": report["diagnosis_detail"],
                        "imputation_explanation": f"Imputed using {report.get('method_used', 'standard method')}: {report.get('rationale', '')}",
                        "confidence_note": "Standard confidence assessment based on sample properties." if not report.get('low_confidence') else "Low confidence due to sample characteristics or high missingness.",
                        "recommended_action": "Verify imputed distribution against domain expectations and check for any remaining outliers."
                    })

            db.add(
                ExplanationResultRow(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    generated_by=result.generated_by,
                    overall_summary=result.explanation.overall_summary,
                    columns_json=columns_json,
                )
            )
            db.commit()
            emit_to_job(job_id, "job:log", {"message": "Explanation generated and saved successfully"})
        except Exception as explain_exc:
            logger.warning("Explanation generation failed (%s), saving analytical fallback to database.", explain_exc)
            from app.core.llm_explainer import _generate_fallback_explanation
            fb_result = _generate_fallback_explanation(column_reports)
            db.add(
                ExplanationResultRow(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    generated_by=fb_result.generated_by,
                    overall_summary=fb_result.explanation.overall_summary,
                    columns_json=[col.model_dump() for col in fb_result.explanation.columns],
                )
            )
            db.commit()
            emit_to_job(job_id, "job:log", {"message": "Analytical fallback explanation generated and saved successfully"})

        # ── Done ───────────────────────────────────────────────────────
        job.status = JobStatus.COMPLETE
        job.completed_at = _now()
        db.commit()

        emit_to_job(job_id, "job:phase", {"phase": "complete", "message": "All processing complete"})
        emit_to_job(job_id, "job:complete", {"dataset_id": dataset_id})

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        error_msg = f"{exc}\n{traceback.format_exc()}"
        logger.error("Approved pipeline failed for job %s: %s", job_id, error_msg)

        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = error_msg
            job.completed_at = _now()
            db.commit()

        emit_to_job(job_id, "job:error", {"message": str(exc)})
    finally:
        db.close()
