"""Validated browser response contract for SolarSleuth."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=12000)
    observations: list[str] = Field(default_factory=list, max_length=100)
    possible_causes: list[str] = Field(default_factory=list, max_length=100)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=100)
    recommended_checks: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    confidence: Literal["low", "moderate", "high", "insufficient_evidence"] = "insufficient_evidence"


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    plant_id: str
    model: str = Field(min_length=1, max_length=256)
    analysis: Analysis
    ml_analysis: dict[str, Any] | None = None
    analysis_mode: str | None = None
