"""
routes_imputation.py

Handles triggering imputation jobs, fetching final results, and downloading imputed CSVs.
"""

from __future__ import annotations

import os
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.db_models import Dataset, Job, JobStatus, JobType, DiagnosisResult, ImputationResult
from app.core.job_runner import run_imputation_job
from app.schemas.models import JobResponse, DatasetResultsResponse, DiagnosisResultResponse, ImputationResultResponse

router = APIRouter()


@router.post("/{dataset_id}", response_model=JobResponse)
async def run_imputation(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobResponse:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Create new background job
    job = Job(
        dataset_id=dataset.id,
        job_type=JobType.IMPUTE,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch to background task runner
    background_tasks.add_task(run_imputation_job, job.id)

    return JobResponse.model_validate(job)


@router.get("/{dataset_id}/results", response_model=DatasetResultsResponse)
async def get_imputation_results(
    dataset_id: str,
    db: Session = Depends(get_db)
) -> DatasetResultsResponse:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    diag_results = db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset_id).all()
    imp_results = db.query(ImputationResult).filter(ImputationResult.dataset_id == dataset_id).all()

    return DatasetResultsResponse(
        dataset_id=dataset.id,
        filename=dataset.filename,
        row_count=dataset.row_count,
        column_names=dataset.column_names,
        diagnosis_results=[DiagnosisResultResponse.model_validate(d) for d in diag_results],
        imputation_results=[ImputationResultResponse.model_validate(i) for i in imp_results],
    )


@router.get("/{dataset_id}/download")
async def download_imputed_file(
    dataset_id: str,
    db: Session = Depends(get_db)
) -> FileResponse:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    imp_result = db.query(ImputationResult).filter(ImputationResult.dataset_id == dataset_id).first()
    if not imp_result or not imp_result.imputed_file_path or not os.path.exists(imp_result.imputed_file_path):
        raise HTTPException(status_code=404, detail="Imputed file not found. Ensure imputation completed successfully.")

    return FileResponse(
        path=imp_result.imputed_file_path,
        filename=f"imputed_{dataset.filename}",
        media_type="text/csv",
    )
