"""Counterfactual accounting for energy loss and performance waterfalls.

The waterfall is defined as:

    F = forecast energy
    E = weather-adjusted expected energy under actual weather
    A = actual measured energy

    weather_effect = E - F
    plant_effect = A - E
    total_deviation = A - F

The signed components must reconcile within a small tolerance.  The module is
strict about units and interval resolution so it does not silently build false
values from incompatible inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pandas as pd

DEFAULT_TOLERANCE_KWH = 1e-6

ENERGY_UNITS = {"kwh", "wh", "mwh", "kilo_watt_hour", "watt_hour"}
POWER_UNITS = {"kw", "w", "mw", "kilowatt", "watt", "megawatt"}


@dataclass
class EnergyLedger:
    """Stores energy-loss transactions by source and duration.

    Only one primary cause is allowed per interval.  This prevents overlapping
    root causes from being double counted in the energy ledger.
    """

    events: list[dict[str, Any]] = field(default_factory=list)

    def add_event(
        self,
        source: str,
        loss_kwh: float,
        reason: str,
        *,
        interval_id: str | None = None,
        primary: bool = False,
    ) -> None:
        if primary and interval_id is not None:
            for event in self.events:
                if event.get("interval_id") == interval_id and bool(event.get("primary")):
                    raise ValueError(
                        "Only one primary cause is permitted per interval for energy accounting."
                    )
        self.events.append(
            {
                "source": source,
                "loss_kwh": float(loss_kwh),
                "reason": reason,
                "interval_id": interval_id,
                "primary": bool(primary),
            }
        )

    def total_loss_kwh(self) -> float:
        return sum(float(event["loss_kwh"]) for event in self.events)

    def primary_loss_kwh(self) -> float:
        return sum(
            float(event["loss_kwh"])
            for event in self.events
            if bool(event.get("primary"))
        )


class Waterfall:
    """Arithmetic helper for forecasting and counterfactual energy decomposition."""

    @staticmethod
    def aggregate(losses: Iterable[float]) -> float:
        return float(sum(float(loss) for loss in losses))

    @staticmethod
    def percent_of_total(losses: Iterable[float]) -> list[float]:
        values = [float(loss) for loss in losses]
        total = sum(values)
        if total == 0:
            return [0.0 for _ in values]
        return [value / total for value in values]

    @staticmethod
    def _normalize_unit(unit: str | None) -> str | None:
        if unit is None:
            return None
        text = str(unit).strip().lower().replace(" ", "_").replace("-", "_")
        if text in {"kwh", "kilowatt_hour", "kilowatthour"}:
            return "kwh"
        if text in {"wh", "watt_hour", "watthour"}:
            return "wh"
        if text in {"mwh", "megawatt_hour", "megawatthour"}:
            return "mwh"
        if text in {"kw", "kilowatt", "kilowatts"}:
            return "kw"
        if text in {"w", "watt", "watts"}:
            return "w"
        if text in {"mw", "megawatt", "megawatts"}:
            return "mw"
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    @staticmethod
    def convert_to_kwh(
        value: Any,
        *,
        unit: str | None,
        interval_hours: float | None,
    ) -> tuple[float | None, str | None]:
        """Convert numeric input into kWh.

        Power values are converted by multiplying by interval duration. Energy
        values are accepted as-is. Unsupported or missing unit combinations are
        reported as unavailable rather than silently assumed.
        """

        numeric = Waterfall._to_float(value)
        if numeric is None:
            return None, "Input is missing or non-numeric."

        normalized_unit = Waterfall._normalize_unit(unit)
        if normalized_unit is None:
            return None, "Unsupported unit for energy conversion."

        if normalized_unit in ENERGY_UNITS:
            if normalized_unit == "wh":
                return numeric / 1000.0, None
            if normalized_unit == "mwh":
                return numeric * 1000.0, None
            return numeric, None

        if normalized_unit in POWER_UNITS:
            if interval_hours is None:
                return None, "Interval duration is required to convert power to energy."
            interval_value = Waterfall._to_float(interval_hours)
            if interval_value is None or interval_value <= 0:
                return None, "Interval duration must be a positive number of hours."
            if normalized_unit == "w":
                numeric = numeric / 1000.0
            elif normalized_unit == "mw":
                numeric = numeric * 1000.0
            return numeric * interval_value, None

        return None, "Unit is incompatible with the energy/power semantics."

    @staticmethod
    def aggregate_energy_to_resolution(
        values: Sequence[float],
        *,
        source_interval_hours: float,
        target_interval_hours: float,
    ) -> tuple[float | None, str | None]:
        """Aggregate energy to the forecast resolution.

        This method only allows aggregation to a coarser resolution. It never
        up-samples a forecast or silently fills missing periods.
        """

        if source_interval_hours <= 0 or target_interval_hours <= 0:
            return None, "Interval durations must be positive."
        if source_interval_hours > target_interval_hours:
            return None, "Forecast alignment cannot upsample; aggregate to the coarser resolution."

        ratio = target_interval_hours / source_interval_hours
        if not math.isclose(ratio, round(ratio), rel_tol=1e-9, abs_tol=1e-9):
            return None, "Forecast periods are not aligned to a common resolution."

        if not values:
            return 0.0, None
        total = 0.0
        for value in values:
            numeric = Waterfall._to_float(value)
            if numeric is None:
                return None, "One or more values are missing during forecast alignment."
            total += numeric
        return total, None

    @staticmethod
    def reconcile(
        forecast_kwh: Any,
        expected_kwh: Any,
        actual_kwh: Any,
        *,
        tolerance_kwh: float = DEFAULT_TOLERANCE_KWH,
    ) -> dict[str, Any]:
        """Compute the weather/plant decomposition of the total deviation."""

        def unavailable(reason: str) -> dict[str, Any]:
            return {
                "status": "unavailable",
                "reason": reason,
                "forecast_energy_kwh": None,
                "expected_energy_kwh": None,
                "actual_energy_kwh": None,
                "weather_effect_kwh": None,
                "plant_effect_kwh": None,
                "total_deviation_kwh": None,
                "observed_deviation_kwh": None,
                "estimated_anomaly_energy_kwh": None,
                "potentially_recoverable_energy_kwh": None,
                "reconciled": False,
                "tolerance_kwh": float(tolerance_kwh),
                "limitations": [
                    "The waterfall is unavailable because required inputs or units are unsupported."
                ],
            }

        forecast = Waterfall._to_float(forecast_kwh)
        expected = Waterfall._to_float(expected_kwh)
        actual = Waterfall._to_float(actual_kwh)
        if forecast is None or expected is None or actual is None:
            return unavailable("Forecast, expected, or actual energy is missing.")

        weather_effect = expected - forecast
        plant_effect = actual - expected
        total_deviation = actual - forecast
        delta = abs((weather_effect + plant_effect) - total_deviation)
        reconciled = delta <= abs(float(tolerance_kwh))
        estimated_anomaly = max(0.0, expected - actual)
        potentially_recoverable = estimated_anomaly
        result = {
            "status": "ok" if reconciled else "warning",
            "reason": (
                "Waterfall reconciles within tolerance."
                if reconciled
                else "Waterfall does not reconcile within tolerance; check input consistency."
            ),
            "forecast_energy_kwh": forecast,
            "expected_energy_kwh": expected,
            "actual_energy_kwh": actual,
            "weather_effect_kwh": weather_effect,
            "plant_effect_kwh": plant_effect,
            "total_deviation_kwh": total_deviation,
            "observed_deviation_kwh": total_deviation,
            "estimated_anomaly_energy_kwh": estimated_anomaly,
            "potentially_recoverable_energy_kwh": potentially_recoverable,
            "reconciled": reconciled,
            "tolerance_kwh": float(tolerance_kwh),
            "limitations": [
                "Potentially recoverable energy is not guaranteed to be recoverable without explicit operational or commercial inputs.",
                "Logged causes are only a causal hypothesis unless supported by interval evidence."
            ],
        }
        return result

    @staticmethod
    def interval_loss(
        forecast_kwh: Any,
        expected_kwh: Any,
        actual_kwh: Any,
        *,
        primary_cause: str | None = None,
        tolerance_kwh: float = DEFAULT_TOLERANCE_KWH,
    ) -> dict[str, Any]:
        """Convenience wrapper that keeps the scalar waterfall arithmetic explicit."""

        result = Waterfall.reconcile(
            forecast_kwh,
            expected_kwh,
            actual_kwh,
            tolerance_kwh=tolerance_kwh,
        )
        result["primary_cause"] = primary_cause
        return result


def _stack_loss_entries(causes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = []
    seen_primary: set[str] = set()
    for cause in causes:
        interval_id = cause.get("interval_id")
        primary = bool(cause.get("primary"))
        if primary:
            if interval_id is not None and interval_id in seen_primary:
                continue
            if interval_id is not None:
                seen_primary.add(interval_id)
        ordered.append(cause)
    return ordered


def compute_waterfall(
    forecast_kwh: Any,
    expected_kwh: Any,
    actual_kwh: Any,
    *,
    causes: Sequence[dict[str, Any]] | None = None,
    tolerance_kwh: float = DEFAULT_TOLERANCE_KWH,
) -> dict[str, Any]:
    """Return a waterfall and apply single-primary-cause accounting for intervals."""

    result = Waterfall.reconcile(
        forecast_kwh,
        expected_kwh,
        actual_kwh,
        tolerance_kwh=tolerance_kwh,
    )
    if causes is not None:
        result["causes"] = _stack_loss_entries(causes)
        result["primary_causes"] = [
            cause for cause in result["causes"] if bool(cause.get("primary"))
        ]
        result["loss_ledger_kwh"] = sum(
            float(cause.get("loss_kwh", 0.0)) for cause in result["causes"]
        )
    return result

