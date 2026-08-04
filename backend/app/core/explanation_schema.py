from __future__ import annotations

from typing import List
from pydantic import BaseModel


class MechanismExplanation(BaseModel):
    target_column: str
    plain_language_summary: str
    what_this_means_for_the_data: str
    imputation_explanation: str
    confidence_note: str
    recommended_action: str


class DatasetExplanation(BaseModel):
    overall_summary: str
    columns: List[MechanismExplanation]
