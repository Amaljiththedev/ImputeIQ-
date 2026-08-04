"""
routes_diagnosis.py

Handles triggering missingness diagnosis jobs in the background and fetching results.
"""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.db_models import Dataset, Job, JobStatus, JobType, DiagnosisResult
from app.core.job_runner import run_diagnosis_job
from app.schemas.models import JobResponse, DiagnosisResultResponse

router = APIRouter()


@router.post("/{dataset_id}", response_model=JobResponse)
async def run_diagnosis(
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
        job_type=JobType.DIAGNOSE,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch to background task runner
    background_tasks.add_task(run_diagnosis_job, job.id)

    return JobResponse.model_validate(job)


@router.get("/{dataset_id}/results", response_model=List[DiagnosisResultResponse])
async def get_diagnosis_results(
    dataset_id: str,
    db: Session = Depends(get_db)
) -> List[DiagnosisResultResponse]:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    results = db.query(DiagnosisResult).filter(DiagnosisResult.dataset_id == dataset_id).all()
    return [DiagnosisResultResponse.model_validate(r) for r in results]
