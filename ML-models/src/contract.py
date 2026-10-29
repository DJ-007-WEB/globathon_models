"""JSON contract and schema-version validation for pipeline outputs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "1.0.0"
MODEL_VERSION = "1.0.0"
MAPPING_VERSION = "1.0.0"


@dataclass
class ContractOutput:
    """Structured output for the ML pipeline.

    Backward compatibility is preserved with the older ``status`` and
    ``message`` fields while the pipeline output uses the versioned contract
    required by the project specification.
    """

    schema_version: str = SCHEMA_VERSION
    analysis_status: str = "ok"
    interval: dict[str, Any] | None = None
    forecast_energy: float | None = None
    actual_energy: float | None = None
    deviation: float | None = None
    waterfall: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    mapping_version: str = MAPPING_VERSION
    status: str | None = None
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status or self.analysis_status
        payload["message"] = self.message
        payload["metrics"] = self.metrics
        return payload


def build_contract(
    status: str,
    message: str,
    metrics: dict[str, Any] | None = None,
    *,
    analysis_status: str | None = None,
    interval: dict[str, Any] | None = None,
    forecast_energy: float | None = None,
    actual_energy: float | None = None,
    deviation: float | None = None,
    waterfall: dict[str, Any] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    limitations: list[str] | None = None,
    unresolved_fields: list[str] | None = None,
    model_version: str = MODEL_VERSION,
    mapping_version: str = MAPPING_VERSION,
) -> ContractOutput:
    """Build an output payload wrapped in the versioned schema contract."""

    resolved_status = analysis_status or status
    return ContractOutput(
        schema_version=SCHEMA_VERSION,
        analysis_status=resolved_status,
        interval=interval,
        forecast_energy=forecast_energy,
        actual_energy=actual_energy,
        deviation=deviation,
        waterfall=waterfall,
        anomalies=anomalies or [],
        hypotheses=hypotheses or [],
        evidence=evidence or [],
        limitations=limitations or [],
        unresolved_fields=unresolved_fields or [],
        model_version=model_version,
        mapping_version=mapping_version,
        status=status,
        message=message,
        metrics=metrics or {},
    )


def validate_contract(payload: dict[str, Any], schema_path: str | Path | None = None) -> None:
    """Validate the output payload against the project JSON Schema."""

    schema_file = Path(schema_path) if schema_path is not None else Path(__file__).resolve().parents[1] / "configs" / "output_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise ValueError("; ".join(f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors))


def write_contract_json(payload: dict[str, Any], output_path: str | Path) -> Path:
    """Write a contract payload to disk using UTF-8 JSON with newline termination."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
