"""Request and response contracts shared by the API and frontend."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class AnalysisRequest(BaseModel):
    """Payload from the backend orchestrator, including teammate ML outputs."""
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, max_length=128)
    plant_id: str = Field(min_length=1, max_length=128)
    timestamp: str | None = Field(default=None, max_length=128)
    plant_context: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(description="Observed readings, alarms, quality flags, and time-series summaries.")
    ml_results: dict[str, Any] = Field(default_factory=dict, description="Outputs from the separate ML models; preserve original names and values.")
    retrieved_context: list[str] = Field(default_factory=list, max_length=12, description="Optional excerpts from a future retriever; this API does not retrieve documents.")

class AnalysisResponse(BaseModel):
    """Constrained explanation returned by the local LLM."""
    summary: str
    observations: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: Literal["low", "moderate", "high", "insufficient_evidence"] = "insufficient_evidence"

class AnalyzeResponse(BaseModel):
    """Envelope returned to the frontend."""
    request_id: str | None = None
    plant_id: str
    model: str
    analysis: AnalysisResponse
