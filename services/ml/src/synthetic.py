"""Synthetic solar-plant scenario generation and fault injection.

The generator is intentionally simplified and deterministic. It produces
separate model-input files and a separate ground-truth file so that injected
fault labels cannot accidentally become model features.

Physical model (documented assumptions, not a universal plant model)::

    module_temp_c = ambient_temp_c + 0.03 * poa_w_m2

    p_dc_kw = rated_dc_kw * (poa_w_m2 / 1000)
              * (1 + gamma * (module_temp_c - 25))
              * (1 - system_losses_fraction)

    p_ac_kw = min(p_dc_kw * inverter_efficiency, rated_ac_kw)

``poa_w_m2`` is approximated by measured GHI in this version; no transposition,
albedo or spectral model is applied. Power is explicitly gated to zero when
the calculated solar elevation is at or below the horizon, so a faulty
irradiance sensor cannot create nighttime generation.

All timestamps are UTC and are written as ``YYYY-MM-DDTHH:MM:SSZ``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "synthetic"
BATCH_VERSION = "1.0.0"

SCENARIO_KINDS: tuple[str, ...] = (
    "normal",
    "inverter_outage",
    "inverter_derating",
    "performance_drift",
    "sensor_flatline",
    "sensor_offset",
    "curtailment",
    "missing_readings",
    "communication_gap",
)
WEATHER_MODES: tuple[str, ...] = ("clear", "variable", "cloudy", "mixed")
INTERVAL_CHOICES_MINUTES: tuple[int, ...] = (5, 10, 15, 30, 60)
OUTPUT_FILES: tuple[str, ...] = (
    "operating_data.csv",
    "weather.csv",
    "forecast.csv",
    "devices.csv",
    "event_log.csv",
    "ground_truth.csv",
    "metadata.json",
)
GROUND_TRUTH_COLUMNS: tuple[str, ...] = (
    "synthetic",
    "scenario_id",
    "event_id",
    "fault_type",
    "asset_id",
    "start_utc",
    "end_utc",
    "duration_minutes",
    "severity",
    "parameter",
    "value",
    "unit",
    "logged_in_event_log",
    "notes",
)
INPUT_COLUMN_NAMES_TO_KEEP_OUT: frozenset[str] = frozenset(
    {
        "fault_type",
        "ground_truth",
        "is_fault",
        "fault_magnitude",
        "severity",
        "logged_in_event_log",
    }
)


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
        return [
            value + severity * 25.0 if idx % 12 == 0 else value
            for idx, value in enumerate(values)
        ]


def generate_synthetic_series(
    length: int, baseline: Callable[[int], float]
) -> list[float]:
    """Generate a deterministic synthetic time series from a baseline function."""

    return [baseline(i) for i in range(length)]


@dataclass(frozen=True)
class GeneratorConfig:
    """Configuration for a reproducible synthetic batch."""

    seed: int = 42
    n_scenarios: int = 10
    capacity_kw: float | None = None
    inverter_count: int | None = None
    interval_minutes: int | None = None
    days: int = 2
    weather: str = "mixed"
    sensor_noise: float = 0.02
    dc_ac_ratio: float = 1.2
    system_losses: float = 0.12

    def __post_init__(self) -> None:
        if self.n_scenarios < 1:
            raise ValueError("n_scenarios must be at least 1")
        if self.days < 1:
            raise ValueError("days must be at least 1")
        if self.capacity_kw is not None and self.capacity_kw <= 0:
            raise ValueError("capacity_kw must be positive")
        if self.inverter_count is not None and self.inverter_count < 1:
            raise ValueError("inverter_count must be at least 1")
        if self.interval_minutes is not None and self.interval_minutes < 1:
            raise ValueError("interval_minutes must be positive")
        if self.weather not in WEATHER_MODES:
            raise ValueError(f"weather must be one of {WEATHER_MODES}")
        if self.sensor_noise < 0:
            raise ValueError("sensor_noise must be non-negative")
        if self.dc_ac_ratio <= 0:
            raise ValueError("dc_ac_ratio must be positive")
        if not 0 <= self.system_losses < 1:
            raise ValueError("system_losses must be in [0, 1)")


@dataclass
class GeneratedScenario:
    """In-memory scenario with model inputs and separate ground truth."""

    scenario_id: str
    metadata: dict[str, Any]
    operating: pd.DataFrame
    weather: pd.DataFrame
    forecast: pd.DataFrame
    devices: pd.DataFrame
    event_log: pd.DataFrame
    ground_truth: pd.DataFrame


@dataclass
class _WeatherModel:
    frame: pd.DataFrame
    measured_poa: np.ndarray
    measured_ambient: np.ndarray
    solar_elevation: np.ndarray
    clear_sky_ghi: np.ndarray
    ambient_base: np.ndarray
    base_cloud: float


def _iso(timestamp: Any) -> str:
    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _scenario_seed(seed: int, index: int) -> int:
    state = np.random.SeedSequence([int(seed), int(index)]).generate_state(
        1, dtype=np.uint32
    )
    return int(state[0])


def _inverter_ids(count: int) -> list[str]:
    width = max(2, len(str(count)))
    return [f"INV-{index:0{width}d}" for index in range(1, count + 1)]


def _choose_inverter_count(capacity_kw: float, rng: np.random.Generator) -> int:
    if capacity_kw < 250:
        maximum = 2
    elif capacity_kw < 500:
        maximum = 3
    elif capacity_kw < 1500:
        maximum = 4
    else:
        maximum = 6
    return int(rng.integers(1, maximum + 1))


def _choose_capacity(rng: np.random.Generator) -> float:
    return float(rng.choice([100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0]))


def _solar_elevation(
    timestamps: pd.DatetimeIndex, latitude_deg: float, longitude_deg: float
) -> np.ndarray:
    days = timestamps.dayofyear.to_numpy(dtype=float)
    hours = (
        timestamps.hour.to_numpy(dtype=float)
        + timestamps.minute.to_numpy(dtype=float) / 60.0
        + timestamps.second.to_numpy(dtype=float) / 3600.0
    )
    declination = np.deg2rad(23.44) * np.sin(2.0 * np.pi * (284.0 + days) / 365.0)
    b = 2.0 * np.pi * (days - 81.0) / 364.0
    equation_of_time = (
        9.87 * np.sin(2.0 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    )
    solar_time = hours + (4.0 * longitude_deg + equation_of_time) / 60.0
    hour_angle = np.deg2rad(15.0 * (solar_time - 12.0))
    latitude = np.deg2rad(latitude_deg)
    sin_elevation = np.sin(latitude) * np.sin(declination) + np.cos(
        latitude
    ) * np.cos(declination) * np.cos(hour_angle)
    return np.degrees(np.arcsin(np.clip(sin_elevation, -1.0, 1.0)))


def _healthy_power(
    poa_w_m2: np.ndarray,
    ambient_c: np.ndarray,
    rated_dc_kw: float,
    rated_ac_kw: float,
    inverter_efficiency: float,
    system_losses: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    poa = np.maximum(poa_w_m2, 0.0)
    module_temp = ambient_c + 0.03 * poa
    temperature_factor = np.clip(1.0 - 0.0035 * (module_temp - 25.0), 0.5, 1.2)
    dc = rated_dc_kw * (poa / 1000.0) * temperature_factor * (1.0 - system_losses)
    dc = np.maximum(dc, 0.0)
    ac = np.minimum(dc * inverter_efficiency, rated_ac_kw)
    return np.maximum(ac, 0.0), dc, module_temp


def _choose_window(
    daylight: np.ndarray,
    length: int,
    interval_minutes: int,
    rng: np.random.Generator,
    hours_min: float,
    hours_max: float,
) -> tuple[int, int]:
    if len(daylight):
        start = int(daylight[int(rng.integers(0, len(daylight)))])
    else:
        start = 0
    duration = max(
        1, int(round(rng.uniform(hours_min, hours_max) * 60.0 / interval_minutes))
    )
    end = min(length, start + duration)
    if end <= start:
        end = min(length, start + 1)
    return start, end


# --- weather, faults and scenario construction ---
def _weather_model(
    timestamps: pd.DatetimeIndex,
    latitude_deg: float,
    longitude_deg: float,
    weather_mode: str,
    sensor_noise: float,
    rng: np.random.Generator,
) -> _WeatherModel:
    n = len(timestamps)
    base_cloud = {"clear": 0.08, "variable": 0.35, "cloudy": 0.65}[weather_mode]
    cloud = np.empty(n, dtype=float)
    cloud[0] = base_cloud
    for index in range(1, n):
        cloud[index] = np.clip(
            0.9 * cloud[index - 1] + 0.1 * base_cloud + rng.normal(0.0, 0.03),
            0.0,
            1.0,
        )

    elevation = _solar_elevation(timestamps, latitude_deg, longitude_deg)
    sin_elevation = np.sin(np.deg2rad(elevation))
    clear_sky_ghi = 1000.0 * np.maximum(sin_elevation, 0.0) ** 1.15
    true_ghi = clear_sky_ghi * (1.0 - 0.65 * cloud)
    measured_ghi = np.clip(
        true_ghi * (1.0 + rng.normal(0.0, sensor_noise, n)), 0.0, 1400.0
    )
    measured_poa = np.clip(
        measured_ghi * (1.0 + rng.normal(0.0, sensor_noise, n)), 0.0, 1400.0
    )

    hour = (
        timestamps.hour.to_numpy(dtype=float)
        + timestamps.minute.to_numpy(dtype=float) / 60.0
    )
    ambient_base = (
        20.0
        + 8.0 * np.sin(2.0 * np.pi * (hour - 9.0) / 24.0)
        + 3.0 * (latitude_deg - 20.0) / 20.0
        - 2.0 * cloud
    )
    measured_ambient = np.clip(
        ambient_base + rng.normal(0.0, 0.4 + 8.0 * sensor_noise, n), -20.0, 60.0
    )
    wind = np.clip(
        2.0
        + 2.0 * np.sin(2.0 * np.pi * (hour - 12.0) / 24.0)
        + np.abs(rng.normal(0.0, 1.5, n)),
        0.0,
        20.0,
    )
    direct_fraction = np.clip(0.85 - 0.7 * cloud, 0.0, 1.0)
    dni = np.where(
        sin_elevation > 0.05,
        true_ghi * direct_fraction / np.maximum(sin_elevation, 0.05),
        0.0,
    )
    dni = np.clip(dni, 0.0, 1100.0)
    dhi = np.clip(true_ghi - dni * np.maximum(sin_elevation, 0.0), 0.0, None)

    frame = pd.DataFrame(
        {
            "timestamp_utc": [_iso(value) for value in timestamps],
            "solar_elevation_deg": elevation,
            "ghi_w_m2": measured_ghi,
            "dni_w_m2": dni,
            "dhi_w_m2": dhi,
            "poa_irradiance_w_m2": measured_poa,
            "ambient_temperature_c": measured_ambient,
            "wind_speed_m_s": wind,
            "cloud_cover_fraction": cloud,
        }
    )
    return _WeatherModel(
        frame=frame,
        measured_poa=measured_poa,
        measured_ambient=measured_ambient,
        solar_elevation=elevation,
        clear_sky_ghi=clear_sky_ghi,
        ambient_base=ambient_base,
        base_cloud=base_cloud,
    )


def _forecast_frame(
    weather: _WeatherModel,
    timestamps: pd.DatetimeIndex,
    interval_minutes: int,
    capacity_kw: float,
    total_rated_dc_kw: float,
    system_losses: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    n = len(timestamps)
    forecast_poa = weather.clear_sky_ghi * (1.0 - 0.55 * weather.base_cloud)
    forecast_poa = np.maximum(forecast_poa, 0.0)
    forecast_ac, _, _ = _healthy_power(
        forecast_poa,
        weather.ambient_base,
        total_rated_dc_kw,
        capacity_kw,
        0.97,
        system_losses,
    )
    forecast_ac = np.clip(
        forecast_ac * (1.0 + rng.normal(0.0, 0.05, n)), 0.0, capacity_kw
    )
    interval_hours = interval_minutes / 60.0
    return pd.DataFrame(
        {
            "timestamp_utc": [_iso(value) for value in timestamps],
            "forecast_ghi_w_m2": forecast_poa,
            "forecast_poa_irradiance_w_m2": forecast_poa,
            "forecast_ambient_temperature_c": weather.ambient_base,
            "forecast_ac_power_kw": forecast_ac,
            "forecast_energy_kwh": forecast_ac * interval_hours,
        }
    )


def _event(
    fault_type: str,
    asset_id: str,
    start: int,
    end: int,
    severity: float,
    parameter: str,
    value: float,
    unit: str,
    notes: str,
    logged: bool = False,
) -> dict[str, Any]:
    return {
        "fault_type": fault_type,
        "asset_id": asset_id,
        "start_index": int(start),
        "end_index": int(end),
        "severity": float(severity),
        "parameter": parameter,
        "value": float(value),
        "unit": unit,
        "notes": notes,
        "logged": bool(logged),
    }


def _build_fault_plan(
    kind: str,
    scenario_index: int,
    length: int,
    interval_minutes: int,
    daylight: np.ndarray,
    measured_poa: np.ndarray,
    device_ids: list[str],
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    if kind == "normal":
        return []

    device = device_ids[int(rng.integers(0, len(device_ids)))]
    if kind in {"inverter_outage", "inverter_derating"}:
        start, end = _choose_window(
            daylight, length, interval_minutes, rng, 1.0, 3.0
        )
        if kind == "inverter_outage":
            return [
                _event(
                    "inverter_outage",
                    device,
                    start,
                    end,
                    1.0,
                    "available_fraction",
                    0.0,
                    "fraction",
                    "Full inverter outage during the event window.",
                )
            ]
        available = float(rng.uniform(0.45, 0.80))
        return [
            _event(
                "inverter_derating",
                device,
                start,
                end,
                1.0 - available,
                "available_fraction",
                available,
                "fraction",
                "Partial inverter derating during the event window.",
            )
        ]

    if kind == "performance_drift":
        start = max(0, int(length * 0.2))
        end = max(start + 1, int(length * 0.85))
        loss = float(rng.uniform(0.08, 0.20))
        return [
            _event(
                "performance_drift",
                device,
                start,
                end,
                loss,
                "efficiency_loss_fraction",
                loss,
                "fraction",
                "Linear soiling-like drift; simulated rain reset at event end.",
            )
        ]

    if kind in {"sensor_flatline", "sensor_offset"}:
        start, end = _choose_window(
            daylight, length, interval_minutes, rng, 1.0, 2.0
        )
        if kind == "sensor_flatline":
            value = float(measured_poa[start])
            return [
                _event(
                    "sensor_flatline",
                    "poa_sensor",
                    start,
                    end,
                    1.0,
                    "flatline_value_w_m2",
                    value,
                    "W/m2",
                    "POA sensor held at its value at the event start.",
                )
            ]
        offset = float(rng.uniform(40.0, 120.0))
        return [
            _event(
                "sensor_offset",
                "poa_sensor",
                start,
                end,
                offset,
                "offset_w_m2",
                offset,
                "W/m2",
                "Positive offset added to the POA sensor during the event.",
            )
        ]

    if kind == "curtailment":
        start, end = _choose_window(
            daylight, length, interval_minutes, rng, 2.0, 4.0
        )
        cap_fraction = float(rng.uniform(0.35, 0.70))
        logged = bool(rng.random() < 0.5)
        return [
            _event(
                "curtailment",
                "PLANT",
                start,
                end,
                1.0 - cap_fraction,
                "cap_fraction",
                cap_fraction,
                "fraction",
                "Plant output capped by a grid/operator instruction.",
                logged=logged,
            )
        ]

    if kind == "missing_readings":
        rate = float(rng.uniform(0.02, 0.05))
        return [
            _event(
                "missing_readings",
                "operating_data",
                0,
                length,
                rate,
                "cell_missing_fraction",
                rate,
                "fraction",
                "Random operating readings are missing; missing values are not zero.",
            )
        ]

    if kind == "communication_gap":
        start, end = _choose_window(
            daylight, length, interval_minutes, rng, 1.0, 3.0
        )
        duration = float((end - start) * interval_minutes)
        return [
            _event(
                "communication_gap",
                device,
                start,
                end,
                1.0,
                "gap_duration_minutes",
                duration,
                "minutes",
                "Telemetry is unavailable for the affected inverter.",
            )
        ]

    raise ValueError(f"Unknown scenario kind: {kind}")


def _apply_sensor_faults(
    measured_poa: np.ndarray, events: Sequence[dict[str, Any]]
) -> np.ndarray:
    poa = measured_poa.copy()
    for event in events:
        start = event["start_index"]
        end = event["end_index"]
        if event["fault_type"] == "sensor_flatline":
            poa[start:end] = event["value"]
        elif event["fault_type"] == "sensor_offset":
            poa[start:end] = np.clip(poa[start:end] + event["value"], 0.0, 1400.0)
    return poa


def _ground_truth_rows(
    scenario_id: str,
    events: Sequence[dict[str, Any]],
    timestamps: pd.DatetimeIndex,
    interval_minutes: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not events:
        rows.append(
            {
                "synthetic": True,
                "scenario_id": scenario_id,
                "event_id": "GT-001",
                "fault_type": "normal",
                "asset_id": "PLANT",
                "start_utc": _iso(timestamps[0]),
                "end_utc": _iso(timestamps[-1]),
                "duration_minutes": int(len(timestamps) * interval_minutes),
                "severity": 0.0,
                "parameter": "none",
                "value": 0.0,
                "unit": "none",
                "logged_in_event_log": False,
                "notes": "No injected fault.",
            }
        )
    else:
        for index, event in enumerate(events, start=1):
            start = int(event["start_index"])
            end = int(event["end_index"])
            rows.append(
                {
                    "synthetic": True,
                    "scenario_id": scenario_id,
                    "event_id": f"GT-{index:03d}",
                    "fault_type": event["fault_type"],
                    "asset_id": event["asset_id"],
                    "start_utc": _iso(timestamps[start]),
                    "end_utc": _iso(timestamps[max(start, end - 1)]),
                    "duration_minutes": int((end - start) * interval_minutes),
                    "severity": float(event["severity"]),
                    "parameter": event["parameter"],
                    "value": float(event["value"]),
                    "unit": event["unit"],
                    "logged_in_event_log": bool(event["logged"]),
                    "notes": event["notes"],
                }
            )
    return pd.DataFrame(rows, columns=list(GROUND_TRUTH_COLUMNS))


def _event_log_frame(
    scenario_id: str,
    events: Sequence[dict[str, Any]],
    timestamps: pd.DatetimeIndex,
    interval_minutes: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event["fault_type"] == "curtailment" and event["logged"]:
            rows.append(
                {
                    "synthetic": True,
                    "scenario_id": scenario_id,
                    "event_id": f"EVT-{len(rows) + 1:03d}",
                    "start_utc": _iso(timestamps[event["start_index"]]),
                    "end_utc": _iso(
                        timestamps[max(event["start_index"], event["end_index"] - 1)]
                    ),
                    "event_type": "grid_curtailment",
                    "asset_id": "PLANT",
                    "description": "Grid operator curtailment instruction.",
                    "source": "grid_operator",
                }
            )

    # An event-log entry that has no observable generation impact.
    if rng.random() < 0.40:
        end = min(
            len(timestamps),
            max(1, int(round(2.0 * 60.0 / max(interval_minutes, 1)))),
        )
        rows.append(
            {
                "synthetic": True,
                "scenario_id": scenario_id,
                "event_id": f"EVT-{len(rows) + 1:03d}",
                "start_utc": _iso(timestamps[0]),
                "end_utc": _iso(timestamps[end - 1]),
                "event_type": "scheduled_maintenance",
                "asset_id": "PLANT",
                "description": "Planned maintenance window; no generation impact expected.",
                "source": "maintenance_plan",
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "synthetic",
            "scenario_id",
            "event_id",
            "start_utc",
            "end_utc",
            "event_type",
            "asset_id",
            "description",
            "source",
        ],
    )


# --- scenario assembly and output ---
def _build_scenario(config: GeneratorConfig, index: int) -> GeneratedScenario:
    scenario_seed = _scenario_seed(config.seed, index)
    rng = np.random.default_rng(scenario_seed)
    kind = SCENARIO_KINDS[index % len(SCENARIO_KINDS)]
    scenario_id = f"scenario_{index:03d}"

    capacity_kw = (
        float(config.capacity_kw)
        if config.capacity_kw is not None
        else _choose_capacity(rng)
    )
    inverter_count = (
        int(config.inverter_count)
        if config.inverter_count is not None
        else _choose_inverter_count(capacity_kw, rng)
    )
    interval_minutes = (
        int(config.interval_minutes)
        if config.interval_minutes is not None
        else int(rng.choice(INTERVAL_CHOICES_MINUTES))
    )
    weather_mode = (
        str(rng.choice(["clear", "variable", "cloudy"]))
        if config.weather == "mixed"
        else config.weather
    )
    latitude_deg = float(rng.uniform(5.0, 40.0))
    longitude_deg = float(rng.uniform(-10.0, 25.0))
    start = pd.Timestamp("2024-01-01T00:00:00Z") + pd.Timedelta(
        days=(index * 7) % 365
    )
    periods = max(1, int(round(config.days * 24.0 * 60.0 / interval_minutes)))
    timestamps = pd.date_range(
        start=start, periods=periods, freq=f"{interval_minutes}min", tz="UTC"
    )

    weather = _weather_model(
        timestamps,
        latitude_deg,
        longitude_deg,
        weather_mode,
        config.sensor_noise,
        rng,
    )
    daylight = np.flatnonzero(weather.solar_elevation > 5.0)
    device_ids = _inverter_ids(inverter_count)
    rated_ac_kw = capacity_kw / inverter_count
    rated_dc_kw = rated_ac_kw * config.dc_ac_ratio

    events = _build_fault_plan(
        kind,
        index,
        len(timestamps),
        interval_minutes,
        daylight,
        weather.measured_poa,
        device_ids,
        rng,
    )
    measured_poa = _apply_sensor_faults(weather.measured_poa, events)
    weather.frame["poa_irradiance_w_m2"] = measured_poa
    effective_poa = np.where(weather.solar_elevation > 0.0, measured_poa, 0.0)
    base_ac, base_dc, base_module_temp = _healthy_power(
        effective_poa,
        weather.measured_ambient,
        rated_dc_kw,
        rated_ac_kw,
        0.97,
        config.system_losses,
    )
    interval_hours = interval_minutes / 60.0
    operating_rows: list[pd.DataFrame] = []

    for device_id in device_ids:
        inverter_factor = np.clip(
            1.0 + rng.normal(0.0, max(config.sensor_noise * 0.25, 0.001), periods),
            0.95,
            1.05,
        )
        ac = np.minimum(base_ac * inverter_factor, rated_ac_kw)
        dc = np.maximum(base_dc * inverter_factor, 0.0)
        module_temp = base_module_temp + rng.normal(0.0, 0.2, periods)

        for event in events:
            start_index = event["start_index"]
            end_index = event["end_index"]
            if event["asset_id"] == device_id:
                if event["fault_type"] == "inverter_outage":
                    ac[start_index:end_index] = 0.0
                    dc[start_index:end_index] = 0.0
                elif event["fault_type"] == "inverter_derating":
                    ac[start_index:end_index] *= event["value"]
                    dc[start_index:end_index] *= event["value"]
                elif event["fault_type"] == "performance_drift":
                    steps = np.arange(start_index, end_index, dtype=float)
                    progress = (steps - start_index) / max(
                        1.0, float(end_index - start_index)
                    )
                    factor = 1.0 - event["value"] * progress
                    ac[start_index:end_index] *= factor
                    dc[start_index:end_index] *= factor

        for event in events:
            if event["fault_type"] != "curtailment":
                continue
            start_index = event["start_index"]
            end_index = event["end_index"]
            cap_kw = rated_ac_kw * event["value"]
            ac[start_index:end_index] = np.minimum(
                ac[start_index:end_index], cap_kw
            )

        energy = ac * interval_hours
        frame = pd.DataFrame(
            {
                "scenario_id": scenario_id,
                "synthetic": True,
                "timestamp_utc": [_iso(value) for value in timestamps],
                "inverter_id": device_id,
                "ac_power_kw": ac,
                "dc_power_kw": dc,
                "energy_kwh": energy,
                "module_temperature_c": module_temp,
                "ambient_temperature_c": weather.measured_ambient,
                "poa_irradiance_w_m2": measured_poa,
            }
        )

        for event in events:
            if (
                event["fault_type"] == "communication_gap"
                and event["asset_id"] == device_id
            ):
                columns = [
                    "ac_power_kw",
                    "dc_power_kw",
                    "energy_kwh",
                    "module_temperature_c",
                    "ambient_temperature_c",
                    "poa_irradiance_w_m2",
                ]
                frame.loc[
                    event["start_index"] : event["end_index"] - 1, columns
                ] = np.nan
        operating_rows.append(frame)

    operating = pd.concat(operating_rows, ignore_index=True)
    for event in events:
        if event["fault_type"] != "missing_readings":
            continue
        mask = rng.random(len(operating)) < event["value"]
        if not mask.any():
            mask[int(rng.integers(0, len(operating)))] = True
        numeric_columns = [
            "ac_power_kw",
            "dc_power_kw",
            "energy_kwh",
            "module_temperature_c",
            "ambient_temperature_c",
            "poa_irradiance_w_m2",
        ]
        operating.loc[mask, numeric_columns] = np.nan

    weather_frame = weather.frame.copy()
    weather_frame.insert(0, "scenario_id", scenario_id)
    weather_frame.insert(1, "synthetic", True)

    forecast = _forecast_frame(
        weather,
        timestamps,
        interval_minutes,
        capacity_kw,
        rated_dc_kw * inverter_count,
        config.system_losses,
        rng,
    )
    forecast.insert(0, "scenario_id", scenario_id)
    forecast.insert(1, "synthetic", True)

    devices = pd.DataFrame(
        [
            {
                "scenario_id": scenario_id,
                "synthetic": True,
                "inverter_id": device_id,
                "rated_ac_power_kw": rated_ac_kw,
                "rated_dc_power_kw": rated_dc_kw,
                "inverter_efficiency": 0.97,
                "dc_ac_ratio": config.dc_ac_ratio,
                "module_temperature_coefficient_per_c": -0.0035,
                "system_losses_fraction": config.system_losses,
                "latitude_deg": latitude_deg,
                "longitude_deg": longitude_deg,
            }
            for device_id in device_ids
        ]
    )

    event_log = _event_log_frame(
        scenario_id, events, timestamps, interval_minutes, rng
    )
    ground_truth = _ground_truth_rows(
        scenario_id, events, timestamps, interval_minutes
    )

    metadata: dict[str, Any] = {
        "synthetic": True,
        "batch_version": BATCH_VERSION,
        "scenario_id": scenario_id,
        "seed": int(config.seed),
        "scenario_seed": int(scenario_seed),
        "scenario_index": int(index),
        "capacity_kw": float(capacity_kw),
        "inverter_count": int(inverter_count),
        "sampling_interval_minutes": int(interval_minutes),
        "days": int(config.days),
        "start_utc": _iso(timestamps[0]),
        "end_utc": _iso(timestamps[-1]),
        "timezone": "UTC",
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "weather_mode": weather_mode,
        "sensor_noise_fraction": float(config.sensor_noise),
        "dc_ac_ratio": float(config.dc_ac_ratio),
        "system_losses_fraction": float(config.system_losses),
        "units": {
            "power": "kW",
            "energy": "kWh",
            "irradiance": "W/m2",
            "temperature": "C",
            "wind_speed": "m/s",
            "duration": "minutes",
        },
        "assumptions": [
            "Simplified PV model; POA is approximated by measured GHI.",
            "No transposition, albedo, spectral or thermal-transient model is applied.",
            "Power is zero when calculated solar elevation is at or below the horizon.",
            "Missing readings and communication gaps are NaN and are never zero-filled.",
            "Ground truth is stored separately from model-input files.",
            "Synthetic results are controlled tests, not field accuracy.",
        ],
        "input_files": [
            "operating_data.csv",
            "weather.csv",
            "forecast.csv",
            "devices.csv",
            "event_log.csv",
            "metadata.json",
        ],
    }

    return GeneratedScenario(
        scenario_id=scenario_id,
        metadata=metadata,
        operating=operating,
        weather=weather_frame,
        forecast=forecast,
        devices=devices,
        event_log=event_log,
        ground_truth=ground_truth,
    )


def generate_scenarios(config: GeneratorConfig) -> list[GeneratedScenario]:
    """Generate scenarios in memory without writing files."""

    return [_build_scenario(config, index) for index in range(config.n_scenarios)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_scenario(scenario: GeneratedScenario, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    frames = {
        "operating_data.csv": scenario.operating,
        "weather.csv": scenario.weather,
        "forecast.csv": scenario.forecast,
        "devices.csv": scenario.devices,
        "event_log.csv": scenario.event_log,
        "ground_truth.csv": scenario.ground_truth,
    }
    for filename, frame in frames.items():
        frame.to_csv(
            directory / filename,
            index=False,
            float_format="%.6f",
            lineterminator="\n",
        )
    _write_json(directory / "metadata.json", scenario.metadata)


def write_scenarios(
    scenarios: Sequence[GeneratedScenario], output_dir: str | Path
) -> dict[str, Any]:
    """Write scenarios and a batch manifest; return the manifest."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        directory = root / f"scenario_{index:03d}"
        _write_scenario(scenario, directory)
        entries.append(
            {
                "scenario_id": scenario.scenario_id,
                "directory": directory.name,
                "seed": scenario.metadata["scenario_seed"],
                "weather_mode": scenario.metadata["weather_mode"],
                "model_input_files": [
                    "operating_data.csv",
                    "weather.csv",
                    "forecast.csv",
                    "devices.csv",
                    "event_log.csv",
                    "metadata.json",
                ],
                "ground_truth_file": "ground_truth.csv",
            }
        )

    manifest: dict[str, Any] = {
        "synthetic": True,
        "batch_version": BATCH_VERSION,
        "seed": int(scenarios[0].metadata["seed"]) if scenarios else 0,
        "n_scenarios": len(scenarios),
        "scenario_count": len(scenarios),
        "files_per_scenario": list(OUTPUT_FILES),
        "scenarios": entries,
    }
    _write_json(root / "manifest.json", manifest)
    return manifest


def generate_batch(
    output_dir: str | Path,
    *,
    seed: int = 42,
    n_scenarios: int = 10,
    capacity_kw: float | None = None,
    inverter_count: int | None = None,
    interval_minutes: int | None = None,
    days: int = 2,
    weather: str = "mixed",
    sensor_noise: float = 0.02,
    dc_ac_ratio: float = 1.2,
    system_losses: float = 0.12,
) -> dict[str, Any]:
    """Generate and write a reproducible synthetic batch."""

    config = GeneratorConfig(
        seed=seed,
        n_scenarios=n_scenarios,
        capacity_kw=capacity_kw,
        inverter_count=inverter_count,
        interval_minutes=interval_minutes,
        days=days,
        weather=weather,
        sensor_noise=sensor_noise,
        dc_ac_ratio=dc_ac_ratio,
        system_losses=system_losses,
    )
    return write_scenarios(generate_scenarios(config), output_dir)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Generate reproducible synthetic solar-plant scenarios."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-scenarios", type=int, default=10)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--capacity-kw", type=float, default=None)
    parser.add_argument("--inverters", dest="inverter_count", type=int, default=None)
    parser.add_argument("--interval-minutes", type=int, default=None)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument(
        "--weather", choices=WEATHER_MODES, default="mixed"
    )
    parser.add_argument("--sensor-noise", type=float, default=0.02)
    parser.add_argument("--dc-ac-ratio", type=float, default=1.2)
    parser.add_argument("--system-losses", type=float, default=0.12)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a batch and print a short machine-readable summary."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = generate_batch(
            args.out,
            seed=args.seed,
            n_scenarios=args.n_scenarios,
            capacity_kw=args.capacity_kw,
            inverter_count=args.inverter_count,
            interval_minutes=args.interval_minutes,
            days=args.days,
            weather=args.weather,
            sensor_noise=args.sensor_noise,
            dc_ac_ratio=args.dc_ac_ratio,
            system_losses=args.system_losses,
        )
    except ValueError as exc:
        parser.error(str(exc))

    summary = {
        "synthetic": True,
        "out": str(args.out),
        "manifest": str(Path(args.out) / "manifest.json"),
        "seed": args.seed,
        "n_scenarios": manifest["n_scenarios"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
