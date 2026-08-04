from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class MissingnessProfile(BaseModel):
    column: str
    missing_count: int
    missing_pct: float


class DatasetSummary(BaseModel):
    id: str
    filename: str
    row_count: int
    column_count: int
    numeric_columns: List[str]
    categorical_columns: List[str]
    uploaded_at: datetime
    missingness_profile: List[MissingnessProfile]

    class Config:
        from_attributes = True


class JobResponse(BaseModel):
    id: str
    dataset_id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class DiagnosisResultResponse(BaseModel):
    target_column: str
    diagnosed_mechanism: str
    diagnosis_detail: str
    # FIX: must be Optional -- _diagnose_one_column() in diagnose_mechanism.py
    # deliberately returns None for IDENTIFIER columns, which skip Little's
    # test entirely. Without Optional, every dataset containing an ID column
    # (patid, probobsid, etc.) crashes API serialization with a 500 error.
    littles_p_value: Optional[float] = None
    littles_suggests_mcar: Optional[bool] = None
    # FIX: made Optional with a safe default, matching the dict-returning
    # functions in diagnose_mechanism.py which can be legitimately empty.
    categorical_assoc_p_values: Optional[Dict[str, float]] = {}
    numeric_assoc_p_values: Optional[Dict[str, float]] = {}
    significant_drivers: List[str]
    n_missing: int
    recommended_method: Optional[str] = None
    rationale: Optional[str] = None
    available_methods: Optional[List[str]] = None
    is_cautious_default: Optional[bool] = False
    structural_zero_warning: Optional[Dict[str, Any]] = None
    # FIX: added -- without this, semantic_role computed by
    # column_semantics.py and stored on the DB row is silently dropped
    # before it reaches the frontend.
    semantic_role: Optional[str] = None

    class Config:
        from_attributes = True


class ImputationResultResponse(BaseModel):
    target_column: str
    routed_mechanism: str
    method_used: str
    low_confidence: bool
    rationale: str
    n_imputed: int
    created_at: datetime
    # FIX: same gap as DiagnosisResultResponse.
    semantic_role: Optional[str] = None

    class Config:
        from_attributes = True


class DatasetResultsResponse(BaseModel):
    dataset_id: str
    filename: str
    row_count: int
    column_names: List[str]
    diagnosis_results: List[DiagnosisResultResponse]
    imputation_results: List[ImputationResultResponse]
