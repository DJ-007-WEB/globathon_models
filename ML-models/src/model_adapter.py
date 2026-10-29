"""Model-facing adapter contract for a separately developed local AI model.

This module is intentionally model-agnostic. It defines a narrow, safe boundary
between the validated normalized feature table and a teammate's locally running
model, without inventing the model's algorithm, weights, or output semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ModelAdapterResult:
    """Structured result returned by a local-model adapter."""

    status: str
    model_name: str
    predictions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    feature_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)


class LocalModelAdapter:
    """Base adapter contract for a teammate-owned local model.

    The adapter must accept a validated DataFrame, verify required columns, and
    return a safe payload. It must not silently invent a feature, unit conversion,
    or causal claim; any missing required data should fail with a clear warning.
    """

    model_name = "local_model"
    required_columns: tuple[str, ...] = ()

    def validate_frame(self, frame: pd.DataFrame) -> tuple[bool, list[str], list[str]]:
        if frame is None or frame.empty:
            return False, [], ["Frame is empty."]

        missing = [column for column in self.required_columns if column not in frame.columns]
        warnings: list[str] = []
        if missing:
            warnings.append(f"Missing required columns: {', '.join(missing)}.")
        return len(missing) == 0, missing, warnings

    def predict(self, frame: pd.DataFrame) -> ModelAdapterResult:
        raise NotImplementedError("Subclasses must implement predict().")


class StubLocalModelAdapter(LocalModelAdapter):
    """A tiny local stub for integration tests only.

    This is not a production model. It simply binds the expected contract and
    demonstrates how the validated normalized frame can be handed to a local
    teammate model with a safe fallback if required inputs are absent.
    """

    model_name = "local_stub"
    required_columns = ("timestamp_utc", "ac_power_kw", "expected_power_kw")

    def predict(self, frame: pd.DataFrame) -> ModelAdapterResult:
        ok, missing, warnings = self.validate_frame(frame)
        if not ok:
            return ModelAdapterResult(
                status="fallback",
                model_name=self.model_name,
                warnings=warnings,
                error="Model input validation failed.",
                feature_columns=list(frame.columns) if frame is not None else [],
                missing_columns=missing,
            )

        normalized = frame.copy()
        normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], errors="coerce")

        predictions: list[dict[str, Any]] = []
        for _, row in normalized.iterrows():
            actual_kw = pd.to_numeric(row.get("ac_power_kw"), errors="coerce")
            expected_kw = pd.to_numeric(row.get("expected_power_kw"), errors="coerce")
            timestamp_value = row.get("timestamp_utc")
            predictions.append(
                {
                    "timestamp_utc": timestamp_value.isoformat() if pd.notna(timestamp_value) else None,
                    "actual_kw": None if pd.isna(actual_kw) else float(actual_kw),
                    "expected_kw": None if pd.isna(expected_kw) else float(expected_kw),
                    "residual_kw": None if pd.isna(actual_kw) or pd.isna(expected_kw) else float(actual_kw - expected_kw),
                    "source": "local_stub",
                    "status": "accepted",
                }
            )

        return ModelAdapterResult(
            status="ok",
            model_name=self.model_name,
            predictions=predictions,
            warnings=warnings,
            feature_columns=list(normalized.columns),
            missing_columns=[],
        )
