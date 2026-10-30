"""Validated frontend/backend and final response contracts."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, max_length=128)
    plant_id: str = Field(min_length=1, max_length=128)
    timestamp: str | None = Field(default=None, max_length=128)
    plant_context: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(min_length=1)
    ml_results: dict[str, Any] = Field(default_factory=dict)
    retrieved_context: list[str] = Field(default_factory=list, max_length=12)


class Analysis(BaseModel):
    summary: str
    observations: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: Literal["low", "moderate", "high", "insufficient_evidence"] = "insufficient_evidence"


class AnalyzeResponse(BaseModel):
    request_id: str
    plant_id: str
    model: str
    analysis: Analysis
    ml_analysis: dict[str, Any] | None = None
    analysis_mode: str | None = None
