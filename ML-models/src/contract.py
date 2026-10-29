"""JSON contract and schema version declarations for output payloads."""

from __future__ import annotations

from dataclasses import dataclass, asdict


SCHEMA_VERSION = "1.0.0"


@dataclass
class ContractOutput:
    """Minimal JSON-safe output structure for the pipeline."""
    schema_version: str
    status: str
    message: str
    metrics: dict

    def to_dict(self) -> dict:
        return asdict(self)


def build_contract(status: str, message: str, metrics: dict | None = None) -> ContractOutput:
    """Build an output payload with the stable schema version."""
    return ContractOutput(
        schema_version=SCHEMA_VERSION,
        status=status,
        message=message,
        metrics=metrics or {},
    )
