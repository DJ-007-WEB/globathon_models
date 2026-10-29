"""Benchmark the physics expected-output baseline on synthetic scenarios.

The benchmark uses a scenario-level train/test split. Physics-baseline inputs
are operating/weather/device columns only. Ground-truth fault labels are not
read by the model path. LightGBM is optional and is not fitted unless it is
installed and demonstrably improves held-out metrics.
"""

import argparse
import json
from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.baseline import physics_baseline  # noqa: E402
from src.config import load_defaults  # noqa: E402

DEFAULT_BATCH = PROJECT_ROOT / "artifacts" / "synthetic_batch"
LEAKAGE_COLUMNS = frozenset(
    {
        "fault_type",
        "ground_truth",
        "is_fault",
        "fault_magnitude",
        "severity",
        "logged_in_event_log",
    }
)


def load_scenario_inputs(scenario_dir: str | Path) -> pd.DataFrame:
    """Load only model-input files for one synthetic scenario.

    The ground-truth file is deliberately never read here.
    """

    directory = Path(scenario_dir)
    operating = pd.read_csv(directory / "operating_data.csv")
    weather = pd.read_csv(directory / "weather.csv")
    devices = pd.read_csv(directory / "devices.csv")

    weather_columns = ["scenario_id", "timestamp_utc", "ghi_w_m2", "solar_elevation_deg"]
    device_columns = [
        "scenario_id",
        "inverter_id",
        "rated_ac_power_kw",
        "rated_dc_power_kw",
        "inverter_efficiency",
        "system_losses_fraction",
        "module_temperature_coefficient_per_c",
    ]
    frame = operating.merge(
        weather[weather_columns],
        on=["scenario_id", "timestamp_utc"],
        how="left",
        validate="many_to_one",
    )
    frame = frame.merge(
        devices[device_columns],
        on=["scenario_id", "inverter_id"],
        how="left",
        validate="many_to_one",
    )
    leaked = LEAKAGE_COLUMNS.intersection(frame.columns)
    if leaked:
        raise ValueError(f"Ground-truth label columns leaked into model inputs: {sorted(leaked)}")
    return frame


def _metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, Any]:
    actual_values = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    predicted_values = pd.to_numeric(predicted, errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(actual_values) & np.isfinite(predicted_values)
    count = int(mask.sum())
    if count == 0:
        return {"count": 0, "mae": None, "rmse": None, "bias": None}
    error = predicted_values[mask] - actual_values[mask]
    return {
        "count": count,
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
    }


def evaluate_frame(frame: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Run the physics baseline and compare it with observed synthetic output."""

    result = physics_baseline(
        frame,
        config=config,
        poa_column="poa_irradiance_w_m2",
        ghi_column="ghi_w_m2",
        module_temperature_column="module_temperature_c",
        ambient_temperature_column="ambient_temperature_c",
        capacity_column="rated_ac_power_kw",
        dc_capacity_column="rated_dc_power_kw",
        inverter_efficiency_column="inverter_efficiency",
        system_losses_column="system_losses_fraction",
        temperature_coefficient_column="module_temperature_coefficient_per_c",
        timestamp_column="timestamp_utc",
        device_column="inverter_id",
    )
    return {
        "status": result["status"],
        "power": _metrics(frame["ac_power_kw"], result["expected_power_kw"]),
        "energy": _metrics(frame["energy_kwh"], result["expected_energy_kwh"]),
        "warnings": result["warnings"],
        "baseline_columns": result["columns"],
    }


def _combine_metrics(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [metric for metric in metrics if metric and metric.get("count")]
    total = sum(int(metric["count"]) for metric in usable)
    if total == 0:
        return {"count": 0, "mae": None, "rmse": None, "bias": None}
    return {
        "count": total,
        "mae": sum(float(metric["mae"]) * int(metric["count"]) for metric in usable) / total,
        "rmse": float(
            np.sqrt(
                sum(
                    float(metric["rmse"]) ** 2 * int(metric["count"])
                    for metric in usable
                )
                / total
            )
        ),
        "bias": sum(float(metric["bias"]) * int(metric["count"]) for metric in usable)
        / total,
    }


def _aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [result["status"] for result in results]
    if not statuses or "unavailable" in statuses:
        status = "unavailable"
    elif "warning" in statuses:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "power": _combine_metrics([result["power"] for result in results]),
        "energy": _combine_metrics([result["energy"] for result in results]),
        "warnings": sorted(
            {warning for result in results for warning in result["warnings"]}
        ),
        "baseline_columns": results[0]["baseline_columns"] if results else {},
    }


def split_scenarios(
    directories: list[Path], train_fraction: float = 0.6
) -> tuple[list[Path], list[Path]]:
    if not directories:
        return [], []
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between 0 and 1")
    test_count = max(1, int(round(len(directories) * (1.0 - train_fraction))))
    test = directories[-test_count:]
    train = directories[:-test_count]
    if not train:
        train = test[:1]
    return train, test


def run_benchmark(batch_dir: str | Path, train_fraction: float = 0.6) -> dict[str, Any]:
    """Evaluate on scenario-level held-out test scenarios."""

    batch = Path(batch_dir)
    if not batch.is_dir():
        raise FileNotFoundError(f"Synthetic batch not found: {batch}")
    directories = sorted(path for path in batch.iterdir() if path.is_dir())
    if not directories:
        raise FileNotFoundError(f"No scenario directories found in {batch}")
    train_dirs, test_dirs = split_scenarios(directories, train_fraction)
    config = load_defaults()

    frame_cache = {directory.name: load_scenario_inputs(directory) for directory in directories}
    train_frames = [frame_cache[directory.name] for directory in train_dirs]
    test_frames = [frame_cache[directory.name] for directory in test_dirs]
    train_results = [evaluate_frame(frame, config) for frame in train_frames]
    test_results = [evaluate_frame(frame, config) for frame in test_frames]

    train_eval = _aggregate_results(train_results)
    test_eval = _aggregate_results(test_results)

    per_scenario = []
    for directory, result in zip(test_dirs, test_results, strict=True):
        per_scenario.append(
            {
                "scenario_id": directory.name,
                "status": result["status"],
                "power": result["power"],
                "energy": result["energy"],
            }
        )

    warnings = sorted(
        {
            warning
            for result in train_results + test_results
            for warning in result["warnings"]
        }
    )
    lightgbm_available = find_spec("lightgbm") is not None
    lightgbm = {
        "evaluated": False,
        "available": lightgbm_available,
        "reason": (
            "LightGBM is available but was not evaluated in this run; "
            "the physics baseline is retained."
            if lightgbm_available
            else "LightGBM is not installed; the physics baseline is retained."
        ),
    }

    return {
        "batch": str(batch),
        "split": {
            "strategy": "scenario_level",
            "train_scenarios": [directory.name for directory in train_dirs],
            "test_scenarios": [directory.name for directory in test_dirs],
            "train_fraction": train_fraction,
        },
        "physics_baseline": {
            "train": train_eval,
            "test": test_eval,
            "per_test_scenario": per_scenario,
            "warnings": warnings,
        },
        "lightgbm": lightgbm,
        "final_method": "physics_baseline",
        "ground_truth_used_as_input": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the physics expected-output baseline.")
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--train-fraction", type=float, default=0.6)
    args = parser.parse_args()
    result = run_benchmark(args.batch, args.train_fraction)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


