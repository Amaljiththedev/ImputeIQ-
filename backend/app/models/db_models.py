"""
app/models/db_models.py

SQLAlchemy ORM models.

Dataset            -- one row per uploaded CSV
Job                 -- one row per background diagnose/impute run (status + polling)
DiagnosisResult     -- one row per (job, target_column) diagnosis outcome
ImputationResult    -- one row per (job, target_column) imputation outcome

Notes:
- JSON columns (SQLite/Postgres both support JSON via SQLAlchemy's generic
  JSON type) are used for small structured blobs (column lists, p-value
  dicts, driver lists) rather than creating extra tables for these --
  appropriate here since they are written once and read whole, never
  queried by their internal fields.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobType(str, enum.Enum):
    DIAGNOSE = "diagnose"
    IMPUTE = "impute"
    EXPLAIN = "explain"
    PROCESS = "process"
    RECOMMEND = "recommend"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=_uuid)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    row_count = Column(Integer, nullable=False)
    column_names = Column(JSON, nullable=False)  # list[str]
    numeric_columns = Column(JSON, nullable=False)  # list[str]
    categorical_columns = Column(JSON, nullable=False)  # list[str]
    uploaded_at = Column(DateTime(timezone=True), default=_now)
    validated_storage_path = Column(String, nullable=True)  # Optional path where preprocessed copy with converted placeholders is stored
    # User-supplied description of what the columns mean. Overrides the tool's
    # own inference, which otherwise rests on the column name alone.
    data_dictionary = Column(Text, nullable=True)

    jobs = relationship("Job", back_populates="dataset", cascade="all, delete-orphan")
    diagnosis_results = relationship(
        "DiagnosisResult", back_populates="dataset", cascade="all, delete-orphan"
    )
    imputation_results = relationship(
        "ImputationResult", back_populates="dataset", cascade="all, delete-orphan"
    )
    explanation_results = relationship(
        "ExplanationResultRow", back_populates="dataset", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    job_type = Column(Enum(JobType), nullable=False)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    created_at = Column(DateTime(timezone=True), default=_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    dataset = relationship("Dataset", back_populates="jobs")


class DiagnosisResult(Base):
    __tablename__ = "diagnosis_results"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)

    target_column = Column(String, nullable=False)
    diagnosed_mechanism = Column(String, nullable=False)  # "MAR" | "Ambiguous (MCAR/MNAR)"
    diagnosis_detail = Column(Text, nullable=False)
    littles_p_value = Column(Float, nullable=True)
    littles_suggests_mcar = Column(Boolean, nullable=True)
    categorical_assoc_p_values = Column(JSON, nullable=True)
    numeric_assoc_p_values = Column(JSON, nullable=True)
    significant_drivers = Column(JSON, nullable=True)
    n_missing = Column(Integer, nullable=False)
    recommended_method = Column(String, nullable=True)
    is_cautious_default = Column(Boolean, nullable=True)
    rationale = Column(Text, nullable=True)
    available_methods = Column(JSON, nullable=True)
    structural_zero_warning = Column(JSON, nullable=True)
    semantic_role = Column(String, nullable=True)  # "identifier" | "categorical" | "continuous"
    created_at = Column(DateTime(timezone=True), default=_now)

    dataset = relationship("Dataset", back_populates="diagnosis_results")


class ImputationResult(Base):
    __tablename__ = "imputation_results"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)

    target_column = Column(String, nullable=False)
    routed_mechanism = Column(String, nullable=False)  # normalised MCAR/MAR/MNAR used for routing
    method_used = Column(String, nullable=False)
    low_confidence = Column(Boolean, nullable=False)
    rationale = Column(Text, nullable=False)
    semantic_role = Column(String, nullable=True)  # "identifier" | "categorical" | "continuous"
    n_imputed = Column(Integer, nullable=False)
    # Cells the method declined to fill, and why. Imputation within measurement
    # strata has no donor for a stratum where nothing was ever observed, and
    # borrowing one would invent a value on a scale never seen for that
    # measurement. Leaving those missing is correct; saying nothing about it
    # is not, since the download then has gaps with no explanation.
    n_unimputable = Column(Integer, nullable=True, default=0)
    unimputable_reason = Column(Text, nullable=True)
    imputed_file_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    dataset = relationship("Dataset", back_populates="imputation_results")


class ExplanationResultRow(Base):
    __tablename__ = "explanation_results"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)

    generated_by = Column(String, nullable=False)  # "language_model" | "template_fallback"
    overall_summary = Column(Text, nullable=False)
    columns_json = Column(JSON, nullable=False)  # list[dict]
    created_at = Column(DateTime(timezone=True), default=_now)

    dataset = relationship("Dataset", back_populates="explanation_results")


class ValidationDecisionCache(Base):
    """
    Caches semantic validation decisions for column placeholder values.
    Ensures repeated uploads or columns across healthcare/finance datasets instantly
    reuse stored decisions without a second model call.
    """
    __tablename__ = "validation_decision_cache"

    id = Column(String, primary_key=True, default=_uuid)
    cache_key = Column(String, unique=True, nullable=False, index=True)  # e.g., "bmi:0:float64"
    column_name = Column(String, nullable=False)
    placeholder_value = Column(String, nullable=False)
    placeholder = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    action = Column(String, nullable=False)  # "replace_with_nan" | "keep"
    source = Column(String, nullable=False, default="language_model")  # "language_model" | "heuristic_fallback"
    created_at = Column(DateTime(timezone=True), default=_now)
