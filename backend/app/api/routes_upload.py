"""
routes_upload.py

Handles CSV file uploads, parses dataset structures, and profiles initial missingness.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.db_models import Dataset
from app.core.missingness_profiling import profile_missingness
from app.schemas.models import DatasetSummary, MissingnessProfile

router = APIRouter()

# Directories relative to backend/app/
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/", response_model=DatasetSummary)
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
) -> DatasetSummary:
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    # Unique dataset id and path
    dataset_id = str(uuid.uuid4())
    storage_path = UPLOAD_DIR / f"{dataset_id}_{file.filename}"

    try:
        content = await file.read()
        with open(storage_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {str(e)}")

    # Read dataset
    try:
        df = pd.read_csv(storage_path, sep=None, engine="python")
    except Exception as e:
        if storage_path.exists():
            storage_path.unlink()
        raise HTTPException(status_code=400, detail=f"Malformed CSV: {str(e)}")

    row_count = len(df)
    column_names = df.columns.tolist()

    # Column type detection
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()

    # Missingness profiling
    profile = profile_missingness(df)
    missingness_profile = [MissingnessProfile(**p) for p in profile]

    # Database record
    dataset = Dataset(
        id=dataset_id,
        filename=file.filename,
        storage_path=str(storage_path),
        row_count=row_count,
        column_names=column_names,
        numeric_columns=numeric_cols,
        categorical_columns=categorical_cols,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return DatasetSummary(
        id=dataset.id,
        filename=dataset.filename,
        row_count=dataset.row_count,
        column_count=len(column_names),
        numeric_columns=dataset.numeric_columns,
        categorical_columns=dataset.categorical_columns,
        uploaded_at=dataset.uploaded_at,
        missingness_profile=missingness_profile,
    )
