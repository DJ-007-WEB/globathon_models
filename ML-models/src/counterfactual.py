"""Counterfactual accounting for energy loss and performance waterfalls."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EnergyLedger:
    """Stores energy-loss transactions by source and duration."""
    events: list[dict] = field(default_factory=list)

    def add_event(self, source: str, loss_kwh: float, reason: str) -> None:
        self.events.append({"source": source, "loss_kwh": float(loss_kwh), "reason": reason})

    def total_loss_kwh(self) -> float:
        return sum(event["loss_kwh"] for event in self.events)


class Waterfall:
    """Arithmetic helper for loss decomposition across stages."""

    @staticmethod
    def aggregate(losses: list[float]) -> float:
        return sum(float(loss) for loss in losses)

    @staticmethod
    def percent_of_total(losses: list[float]) -> list[float]:
        total = sum(float(loss) for loss in losses)
        if total == 0:
            return [0.0 for _ in losses]
        return [float(loss) / total for loss in losses]
