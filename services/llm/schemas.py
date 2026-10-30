"""Bounded request and response contracts for the private local LLM API."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisRequest(BaseModel):
    """Payload from backend: structured observations and bounded ML evidence only."""
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, max_length=128)
    plant_id: str = Field(min_length=1, max_length=128)
    timestamp: str | None = Field(default=None, max_length=128)
    plant_context: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(
        description="Structured observations and ML summary fields supplied by the backend."
    )
    ml_results: dict[str, Any] = Field(
        default_factory=dict,
        description="Authoritative deterministic ML contract; preserve original names and values."
    )
    retrieved_context: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def enforce_payload_budget(self):
        import json
        try:
            encoded = json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False, default=str)
        except (TypeError, ValueError) as exc:
            raise ValueError("Request contains values that cannot be serialized as finite JSON.") from exc
        if len(encoded) > 60000:
            raise ValueError("LLM evidence payload exceeds the 60,000-character limit.")
        if any(len(item) > 4000 for item in self.retrieved_context):
            raise ValueError("Each retrieved context excerpt must be at most 4,000 characters.")
        return self


class AnalysisResponse(BaseModel):
    """Strict structured explanation returned to the backend."""
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=12000)
    observations: list[str] = Field(default_factory=list, max_length=100)
    possible_causes: list[str] = Field(default_factory=list, max_length=100)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=100)
    recommended_checks: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    confidence: Literal["low", "moderate", "high", "insufficient_evidence"] = "insufficient_evidence"


class AnalyzeResponse(BaseModel):
    """Envelope consumed by the application backend."""
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = None
    plant_id: str
    model: str = Field(min_length=1, max_length=256)
    analysis: AnalysisResponse
