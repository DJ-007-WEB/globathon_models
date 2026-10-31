"""Versioned JSON contract for analysis outputs.

Contract version 2 separates *what was observed* from *what was inferred* and
from *what could not be determined*.  Missing values are represented as JSON
``null``; they are never converted to zero.  Status values are closed enums so a
consumer can validate the payload without guessing at legacy strings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "2.1.0"
MODEL_VERSION = "1.0.0"
MAPPING_VERSION = "1.0.0"

ANALYSIS_STATUSES = {"success", "partial", "invalid_input", "failed"}
ANALYSIS_MODES = {"snapshot", "full"}
ENERGY_STATUSES = {"available", "partial", "unavailable", "not_applicable"}
CAPABILITY_STATUSES = {"available", "unavailable", "not_applicable"}
WATERFALL_STATUSES = {"ok", "warning", "unavailable"}

_LEGACY_STATUS = {
    "ok": "success",
    "warning": "partial",
    "unavailable": "partial",
}


@dataclass
class ContractOutput:
    """Structured, versioned output for the ML analysis boundary."""

    schema_version: str = SCHEMA_VERSION
    analysis_status: str = "success"
    analysis_mode: str = "full"
    summary: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    interval: dict[str, Any] = field(default_factory=dict)
    energy: dict[str, Any] = field(default_factory=dict)
    device_performance: list[dict[str, Any]] = field(default_factory=list)
    forecast_energy: float | None = None
    expected_energy: float | None = None
    actual_energy: float | None = None
    deviation: float | None = None
    expected_deviation: dict[str, Any] = field(default_factory=dict)
    expected_deviation_kwh: float | None = None
    waterfall: dict[str, Any] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    missing_required_fields: list[str] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    model_version: str = MODEL_VERSION
    mapping_version: str = MAPPING_VERSION
    config_version: str = ""
    vocab_version: str = ""
    method: str = "physics_baseline"
    model_status: str = "physics_baseline_active"
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_contract(
    status: str | None = None,
    message: str | None = None,
    metrics: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ContractOutput:
    """Build an output payload wrapped in the versioned contract.

    ``status`` and ``message`` are accepted only for source compatibility with
    callers written against contract v1.  New code should use the explicit
    keyword arguments.  ``metrics`` is intentionally not serialized because v2
    exposes typed request, interval, quality and capability sections instead of
    an untyped bag.
    """

    del metrics
    if status is not None and "analysis_status" not in kwargs:
        kwargs["analysis_status"] = _LEGACY_STATUS.get(status, status)
    if message is not None and "summary" not in kwargs:
        kwargs["summary"] = message

    allowed = set(ContractOutput.__dataclass_fields__)
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise TypeError(f"Unsupported contract fields: {', '.join(unknown)}")
    return ContractOutput(**kwargs)


def validate_contract(payload: dict[str, Any], schema_path: str | Path | None = None) -> None:
    """Validate the output payload against the project JSON Schema."""

    schema_file = (
        Path(schema_path)
        if schema_path is not None
        else Path(__file__).resolve().parents[1] / "configs" / "output_schema.json"
    )
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            "; ".join(
                f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
                for error in errors
            )
        )


def write_contract_json(payload: dict[str, Any], output_path: str | Path) -> Path:
    """Write a contract payload to disk using UTF-8 JSON with newline termination."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path
