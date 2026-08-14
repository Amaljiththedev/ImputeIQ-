"""
app/schemas/schemas.py

Pydantic models defining API request/response shapes. Kept separate from
the SQLAlchemy ORM models (app/models/db_models.py) so the API's public
contract can evolve independently of the DB schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    row_count: int
    column_names: list[str]
    numeric_columns: list[str]
    categorical_columns: list[str]
    uploaded_at: datetime
    validated_storage_path: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    current_phase: str | None = None


class DiagnosisResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_column: str
    diagnosed_mechanism: str
    diagnosis_detail: str
    littles_p_value: float | None = None
    littles_suggests_mcar: bool | None = None
    categorical_assoc_p_values: dict[str, float | None] | None = {}
    numeric_assoc_p_values: dict[str, float | None] | None = {}
    significant_drivers: list[str] | None = []
    n_missing: int
    recommended_method: str | None = None
    rationale: str | None = None
    available_methods: list[str] | None = None
    is_cautious_default: bool | None = False
    structural_zero_warning: dict | None = None
    # FIX: added -- without this, semantic_role (identifier/categorical/
    # continuous) computed by column_semantics.py and stored on the DB row
    # is silently dropped before it ever reaches the frontend, since
    # Pydantic's from_attributes=True only serializes declared fields.
    semantic_role: str | None = None


class RecommendationClarifyRequest(BaseModel):
    target_column: str
    question: str


class RecommendationClarifyResponse(BaseModel):
    answer: str


class ApproveImputationRequest(BaseModel):
    method_overrides: dict[str, str] = {}


class ImputationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_column: str
    routed_mechanism: str
    method_used: str
    low_confidence: bool
    rationale: str
    n_imputed: int
    imputed_file_path: str
    # FIX: same gap as DiagnosisResultOut -- semantic_role must be exposed
    # here too, otherwise the imputation report can't show the user why a
    # column was routed to "flag_only" or "mode" instead of median/mice.
    semantic_role: str | None = None


class ExplanationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    generated_by: str
    overall_summary: str
    columns_json: list[dict]


class JobWithDiagnosisOut(JobOut):
    results: list[DiagnosisResultOut] = []


class JobWithImputationOut(JobOut):
    results: list[ImputationResultOut] = []


class JobWithExplanationOut(JobOut):
    result: ExplanationResultOut | None = None


class SensitivityMetricOut(BaseModel):
    column: str
    type: str
    missingCount: int
    missingPct: float
    stabilityScore: int
    status: str
    baselineVal: str
    primaryVal: str
    worstCaseVal: str
    shiftPct: float
    description: str
    scenarioNotes: dict[str, str]


class DatasetResultsOut(BaseModel):
    dataset: DatasetOut
    diagnosis_results: list[DiagnosisResultOut]
    imputation_results: list[ImputationResultOut]
    explanation_results: list[ExplanationResultOut] = []
    sensitivity_metrics: list[SensitivityMetricOut] = []


class ColumnProfileOut(BaseModel):
    """Data profiling statistics for a single column."""
    column: str
    dtype: str
    min: Any | None = None
    max: Any | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    unique_count: int
    null_count: int
    zero_count: int
    empty_string_count: int


class PlaceholderCandidateOut(BaseModel):
    """Suspicious placeholder detected, with the model's semantic recommendation."""
    column: str
    placeholder_value: Any
    count: int
    placeholder: bool
    recommendation: str  # e.g., "Convert to NaN" or "Keep"
    confidence: float
    reason: str
    action: str  # "replace_with_nan" or "keep"


class ColumnAssumptionOut(BaseModel):
    """What the tool believes a variable represents, surfaced for approval.

    Placeholder decisions depend on what a column is taken to mean, and a
    column name can be misleading. Rather than acting on that interpretation
    silently, it is stated per variable so the user can correct it before any
    data is changed.
    """
    column: str
    assumed_meaning: str
    plausible_range: str | None = None
    source: str  # "user_dictionary" | "language_model" | "unavailable"
    needs_review: bool


class ValidationProfileResponse(BaseModel):
    """Response returned when validating/profiling an uploaded dataset before diagnosis."""
    dataset_id: str
    row_count: int
    column_count: int
    duplicate_count: int
    profiles: list[ColumnProfileOut]
    candidates: list[PlaceholderCandidateOut]
    assumptions: list[ColumnAssumptionOut] = []
    has_data_dictionary: bool = False
    detection_method: str = ""


class ValidationReplacementItem(BaseModel):
    """An individual placeholder replacement choice submitted by the user."""
    column: str
    placeholder_value: Any


class ApplyValidationRequest(BaseModel):
    """User submission of approved placeholder-to-NaN conversions prior to diagnosis."""
    replacements: list[ValidationReplacementItem] = []
    assumptions_reviewed: bool = False


class DataDictionaryRequest(BaseModel):
    """A user-supplied description of what the columns mean.

    Free text, one column per line as `column: description`, or JSON mapping
    column names to descriptions. Supplying this replaces the tool's own
    guess at a variable's meaning, which is otherwise inferred from the column
    name and its statistics alone.
    """
    content: str