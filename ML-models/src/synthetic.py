"""Synthetic data generation and fault injection utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class FaultSpec:
    """Configuration for a synthetic degradation or outlier fault."""
    name: str
    severity: float = 1.0
    duration: int = 24
    start_index: int = 0


class FaultLibrary:
    """Library of deterministic fault generation patterns."""

    @staticmethod
    def sag(values: list[float], severity: float = 1.0) -> list[float]:
        return [max(0.0, value * (1.0 - severity * 0.3)) for value in values]

    @staticmethod
    def drift(values: list[float], severity: float = 1.0) -> list[float]:
        return [value * (1.0 + severity * 0.2) for value in values]

    @staticmethod
    def spike(values: list[float], severity: float = 1.0) -> list[float]:
        return [value + severity * 25.0 if idx % 12 == 0 else value for idx, value in enumerate(values)]


def generate_synthetic_series(length: int, baseline: Callable[[int], float]) -> list[float]:
    """Generate a deterministic synthetic time series from a baseline function."""
    return [baseline(i) for i in range(length)]
