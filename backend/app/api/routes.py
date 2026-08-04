"""
app/api/routes.py

API endpoints:
    POST /api/datasets/upload            -> upload CSV, returns DatasetOut
    POST /api/datasets/{id}/diagnose     -> enqueue diagnosis job, returns JobOut (status=pending)
    POST /api/datasets/{id}/impute       -> enqueue imputation job, returns JobOut (status=pending)
    GET  /api/jobs/{job_id}              -> poll job status (+ results once complete)
    GET  /api/datasets/{id}/results      -> fetch all stored diagnosis + imputation results
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.diagnose_mechanism import CATEGORICAL_COLS, NUMERIC_COLS
from app.db import get_db
from app.jobs.runner import (
    run_diagnosis_job,
    run_explanation_job,
    run_full_pipeline,
    run_imputation_job,
    run_recommendation_job,
    run_approved_imputation_and_explanation_job,
)
from app.core.llm_explainer import generate_clarification
from app.core.sensitivity_engine import compute_column_sensitivity
from app.core.validation_service import profile_and_detect_placeholders
from app.models.db_models import (
    Dataset,
    DiagnosisResult,
    ExplanationResultRow,
    ImputationResult,
    Job,
    JobStatus,
    JobType,
)
from app.schemas.schemas import (
    ApplyValidationRequest,
    ApproveImputationRequest,
    DatasetOut,
    DatasetResultsOut,
    DiagnosisResultOut,
    ExplanationResultOut,
    ImputationResultOut,
    JobOut,
    JobWithDiagnosisOut,
    JobWithExplanationOut,
    JobWithImputationOut,
    RecommendationClarifyRequest,
    RecommendationClarifyResponse,
    SensitivityMetricOut,
    ValidationProfileResponse,
)

router = APIRouter(prefix="/api")

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_dataset_or_404(dataset_id: str, db: Session = Depends(get_db)) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def get_job_or_404(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Upload & List Datasets
# ---------------------------------------------------------------------------

@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(
    db: Session = Depends(get_db),
) -> list[Dataset]:
    return db.query(Dataset).order_by(Dataset.uploaded_at.desc()).all()


@router.post("/datasets/upload", response_model=DatasetOut)
async def upload_dataset(
    file: UploadFile,
    db: Session = Depends(get_db),
) -> Dataset:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")

    dataset = Dataset(
        filename=file.filename,
        storage_path="",
        row_count=0,
        column_names=[],
        numeric_columns=[],
        categorical_columns=[],
    )
    db.add(dataset)
    db.flush()  # assigns dataset.id without committing yet

    storage_path = UPLOAD_DIR / f"{dataset.id}_{file.filename}"
    contents = await file.read()
    storage_path.write_bytes(contents)

    try:
        df = pd.read_csv(storage_path, sep=None, engine="python")
    except Exception as exc:
        storage_path.unlink(missing_ok=True)
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc

    # Automatically identify all numeric and categorical columns across any uploaded dataset
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    dataset.storage_path = str(storage_path)
    dataset.row_count = len(df)
    dataset.column_names = df.columns.tolist()
    dataset.numeric_columns = numeric_cols
    dataset.categorical_columns = categorical_cols

    db.commit()
    db.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Data Validation Stage (NEW preprocessing & placeholder detection layer)
# ---------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}/validate", response_model=ValidationProfileResponse)
def get_dataset_validation_profile(
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Profiles the raw CSV dataset and identifies suspicious placeholder candidates.
    Queries Gemini + SQLite cache for semantic recommendations without modifying data.
    """
    return profile_and_detect_placeholders(dataset.storage_path, db, dataset.id)


@router.post("/datasets/{dataset_id}/validate/apply", response_model=JobOut)
def apply_dataset_validation_and_diagnose(
    request: ApplyValidationRequest,
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    """
    Applies user-selected placeholder-to-NaN conversions onto a temporary copy (`validated_df`),
    preserving the original uploaded file. Then enqueues Phase 1 (Diagnosis & Recommendation)
    on the validated data.
    """
    import numpy as np

    df = pd.read_csv(dataset.storage_path, sep=None, engine="python")
    validated_df = df.copy()

    if request.replacements:
        for rep in request.replacements:
            col = rep.column
            val = rep.placeholder_value
            if col not in validated_df.columns:
                continue

            if isinstance(val, str):
                # String sentinels are DETECTED case-insensitively in
                # validation_service.py (it lowercases before matching), so they
                # must be REPLACED case-insensitively too. A plain
                # .replace("unknown", nan) never matches the "Unknown" actually
                # present in the data, which let string placeholders survive
                # cleaning silently. Stripping also covers " N/A " and, for the
                # empty-string candidate, whitespace-only cells.
                target = val.strip().lower()
                validated_df[col] = validated_df[col].apply(
                    lambda x: np.nan
                    if isinstance(x, str) and x.strip().lower() == target
                    else x
                )
            else:
                validated_df[col] = validated_df[col].replace(val, np.nan)

        val_path = UPLOAD_DIR / f"validated_{dataset.id}_{dataset.filename}"
        validated_df.to_csv(val_path, index=False)
        dataset.validated_storage_path = str(val_path)
        db.commit()
    else:
        # If user skipped or chose no replacements, clear any previous validated path
        dataset.validated_storage_path = None
        db.commit()

    # Create and enqueue the RECOMMEND job (Phase 1)
    job = Job(dataset_id=dataset.id, job_type=JobType.RECOMMEND, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_recommendation_job, job.id)
    return job


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/diagnose", response_model=JobOut)
def start_diagnosis(
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    job = Job(dataset_id=dataset.id, job_type=JobType.DIAGNOSE, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_diagnosis_job, job.id)
    return job


# ---------------------------------------------------------------------------
# Impute
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/impute", response_model=JobOut)
def start_imputation(
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    job = Job(dataset_id=dataset.id, job_type=JobType.IMPUTE, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_imputation_job, job.id)
    return job


# ---------------------------------------------------------------------------
# Explain (LLM plain-language layer)
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/explain", response_model=JobOut)
def start_explanation(
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    has_diagnosis = (
        db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).first()
    )
    if not has_diagnosis:
        raise HTTPException(
            status_code=400,
            detail="No diagnosis results found for this dataset. Run /diagnose first.",
        )

    job = Job(dataset_id=dataset.id, job_type=JobType.EXPLAIN, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_explanation_job, job.id)
    return job


# ---------------------------------------------------------------------------
# Unified process (diagnose + impute + explain via Socket.IO)
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/process", response_model=JobOut)
def start_full_pipeline(
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    job = Job(dataset_id=dataset.id, job_type=JobType.PROCESS, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_full_pipeline, job.id)
    return job


# ---------------------------------------------------------------------------
# Recommend (Phase 1 + pause for approval)
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/recommend", response_model=JobOut)
def start_recommendation(
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    job = Job(dataset_id=dataset.id, job_type=JobType.RECOMMEND, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_recommendation_job, job.id)
    return job


# ---------------------------------------------------------------------------
# Approve Imputation & Continue (Phase 2 + Phase 3)
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/impute/approve", response_model=JobOut)
def approve_and_continue_imputation(
    request: ApproveImputationRequest,
    background_tasks: BackgroundTasks,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> Job:
    # Mark the previous RECOMMEND job as complete if awaiting approval
    latest_rec = (
        db.query(Job)
        .filter(Job.dataset_id == dataset.id, Job.job_type == JobType.RECOMMEND)
        .order_by(Job.created_at.desc())
        .first()
    )
    if latest_rec and latest_rec.status == JobStatus.AWAITING_APPROVAL:
        latest_rec.status = JobStatus.COMPLETE
        db.commit()

    # Always create a new PROCESS job for the imputation phase so frontend socket/polling reconnects with a fresh job ID
    job = Job(dataset_id=dataset.id, job_type=JobType.PROCESS, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_approved_imputation_and_explanation_job, job.id, request.method_overrides)
    return job


# ---------------------------------------------------------------------------
# Clarify Recommendation Question via Gemini
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/recommend/clarify", response_model=RecommendationClarifyResponse)
def clarify_recommendation(
    request: RecommendationClarifyRequest,
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> RecommendationClarifyResponse:
    # Get latest diagnosis result for this column
    diag = (
        db.query(DiagnosisResult)
        .filter(DiagnosisResult.dataset_id == dataset.id, DiagnosisResult.target_column == request.target_column)
        .order_by(DiagnosisResult.created_at.desc())
        .first()
    )
    if not diag:
        raise HTTPException(status_code=404, detail=f"No diagnosis found for column '{request.target_column}'")

    answer = generate_clarification(
        target_column=diag.target_column,
        question=request.question,
        mechanism=diag.diagnosed_mechanism,
        diag_detail=diag.diagnosis_detail,
        rec_method=diag.recommended_method or "Standard method",
        rationale=diag.rationale or "Theoretically selected based on mechanism.",
    )
    return RecommendationClarifyResponse(answer=answer)


# ---------------------------------------------------------------------------
# Poll job status
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}")
def get_job(job: Job = Depends(get_job_or_404), db: Session = Depends(get_db)):
    current_phase = "diagnosing"
    if job.status == JobStatus.COMPLETE:
        current_phase = "complete"
    elif job.status == JobStatus.FAILED:
        current_phase = "error"
    elif job.status == JobStatus.AWAITING_APPROVAL:
        current_phase = "awaiting_approval"
    else:
        has_imp = db.query(ImputationResult).filter(ImputationResult.job_id == job.id).first() is not None
        has_diag = db.query(DiagnosisResult).filter(DiagnosisResult.job_id == job.id).first() is not None
        if has_imp:
            current_phase = "explaining"
        elif has_diag:
            current_phase = "imputing"
        else:
            current_phase = "diagnosing"

    job_dict = JobOut.model_validate(job).model_dump()
    job_dict["current_phase"] = current_phase

    if job.job_type in (JobType.DIAGNOSE, JobType.RECOMMEND):
        results = (
            db.query(DiagnosisResult).filter(DiagnosisResult.job_id == job.id).all()
        )
        return JobWithDiagnosisOut(
            **job_dict,
            results=[DiagnosisResultOut.model_validate(r) for r in results],
        )
    elif job.job_type == JobType.IMPUTE:
        results = (
            db.query(ImputationResult).filter(ImputationResult.job_id == job.id).all()
        )
        return JobWithImputationOut(
            **job_dict,
            results=[ImputationResultOut.model_validate(r) for r in results],
        )
    else:  # EXPLAIN or PROCESS
        result = (
            db.query(ExplanationResultRow).filter(ExplanationResultRow.job_id == job.id).first()
        )
        return JobWithExplanationOut(
            **job_dict,
            result=ExplanationResultOut.model_validate(result) if result else None,
        )


# ---------------------------------------------------------------------------
# Fetch all stored results for a dataset
# ---------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}/results", response_model=DatasetResultsOut)
def get_dataset_results(
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> DatasetResultsOut:
    diagnosis_results = (
        db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).all()
    )
    imputation_results = (
        db.query(ImputationResult).filter(ImputationResult.dataset_id == dataset.id).all()
    )
    explanation_results = (
        db.query(ExplanationResultRow).filter(ExplanationResultRow.dataset_id == dataset.id).all()
    )

    sensitivity_metrics_raw = compute_column_sensitivity(dataset, diagnosis_results, imputation_results)

    return DatasetResultsOut(
        dataset=DatasetOut.model_validate(dataset),
        diagnosis_results=[DiagnosisResultOut.model_validate(r) for r in diagnosis_results],
        imputation_results=[ImputationResultOut.model_validate(r) for r in imputation_results],
        explanation_results=[ExplanationResultOut.model_validate(r) for r in explanation_results],
        sensitivity_metrics=[SensitivityMetricOut.model_validate(m) for m in sensitivity_metrics_raw],
    )


@router.get("/datasets/{dataset_id}/sensitivity", response_model=list[SensitivityMetricOut])
def get_dataset_sensitivity(
    dataset: Dataset = Depends(get_dataset_or_404),
    db: Session = Depends(get_db),
) -> list[SensitivityMetricOut]:
    diagnosis_results = (
        db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset.id).all()
    )
    imputation_results = (
        db.query(ImputationResult).filter(ImputationResult.dataset_id == dataset.id).all()
    )
    metrics_raw = compute_column_sensitivity(dataset, diagnosis_results, imputation_results)
    return [SensitivityMetricOut.model_validate(m) for m in metrics_raw]


# ---------------------------------------------------------------------------
# Download imputed CSV
# ---------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}/download")
def download_imputed(dataset: Dataset = Depends(get_dataset_or_404), db: Session = Depends(get_db)):
    res = (
        db.query(ImputationResult)
        .filter(ImputationResult.dataset_id == dataset.id)
        .order_by(ImputationResult.created_at.desc())
        .first()
    )
    if not res or not res.imputed_file_path or not Path(res.imputed_file_path).exists():
        raise HTTPException(
            status_code=404,
            detail="No imputed file found. Trigger and complete an imputation job first.",
        )
    return FileResponse(
        res.imputed_file_path,
        media_type="text/csv",
        filename=f"imputed_{dataset.id}.csv"
    )


@router.get("/datasets/{dataset_id}/missingness-matrix", response_model=dict)
def get_missingness_matrix(
    dataset: Dataset = Depends(get_dataset_or_404),
) -> dict:
    val_path = getattr(dataset, "validated_storage_path", None)
    target_path = val_path if (val_path and Path(val_path).exists()) else dataset.storage_path
    if not target_path or not Path(target_path).exists():
        raise HTTPException(status_code=404, detail="Dataset CSV file not found on disk.")

    df = pd.read_csv(target_path, sep=None, engine="python")
    row_count = len(df)
    missing_cols = [col for col in df.columns if df[col].isna().any()]

    if len(missing_cols) < 2:
        return {"columns": missing_cols, "matrix": [], "row_count": row_count}

    indicator_df = df[missing_cols].isna().astype(int)
    corr = indicator_df.corr().fillna(0.0).round(2)
    matrix = corr.values.tolist()

    return {
        "columns": missing_cols,
        "matrix": matrix,
        "row_count": row_count,
    }
