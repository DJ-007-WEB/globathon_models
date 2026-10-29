import numpy as np
import pandas as pd
import pytest

from src.baseline import physics_baseline, residual_model


def test_units_and_15_minute_energy():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01T12:00:00Z", "2024-01-01T12:15:00Z"], utc=True
            ),
            "poa": [0.8, 0.8],
            "module_temp_f": [77.0, 77.0],
            "capacity_w": [1_000_000.0, 1_000_000.0],
        }
    )
    result = physics_baseline(
        frame,
        poa_column="poa",
        irradiance_unit="kW/m2",
        module_temperature_column="module_temp_f",
        temperature_unit="F",
        capacity_column="capacity_w",
        capacity_unit="W",
        dc_capacity_kw=1200.0,
        inverter_efficiency=1.0,
        system_losses=0.0,
        timestamp_column="timestamp",
        sampling_interval_minutes=15,
    )

    assert result["status"] == "ok"
    assert result["expected_power_kw"].iloc[0] == pytest.approx(960.0)
    assert result["expected_energy_kwh"].iloc[0] == pytest.approx(240.0)


def test_missing_required_inputs_warn_instead_of_estimating():
    ghi_only = pd.DataFrame(
        {
            "ghi_w_m2": [800.0, 0.0],
            "rated_ac_power_kw": [100.0, 100.0],
        }
    )
    result = physics_baseline(ghi_only)

    assert result["status"] == "unavailable"
    assert result["expected_power_kw"].isna().all()
    assert any("POA" in warning for warning in result["warnings"])

    no_capacity = pd.DataFrame({"poa_irradiance_w_m2": [800.0, 0.0]})
    result = physics_baseline(no_capacity)

    assert result["status"] == "unavailable"
    assert result["expected_power_kw"].isna().all()
    assert any("capacity" in warning.lower() for warning in result["warnings"])


def test_nighttime_output_is_zero():
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z"], utc=True
            ),
            "poa_irradiance_w_m2": [0.0, 0.0],
            "module_temperature_c": [15.0, 15.0],
            "rated_ac_power_kw": [100.0, 100.0],
            "rated_dc_power_kw": [120.0, 120.0],
            "inverter_efficiency": [0.97, 0.97],
            "system_losses_fraction": [0.12, 0.12],
            "module_temperature_coefficient_per_c": [-0.0035, -0.0035],
        }
    )
    result = physics_baseline(frame)

    assert result["status"] == "ok"
    assert (result["expected_power_kw"] == 0.0).all()
    assert (result["expected_energy_kwh"] == 0.0).all()


def test_ac_capacity_clipping():
    frame = pd.DataFrame(
        {
            "poa_irradiance_w_m2": [1200.0, 1200.0],
            "module_temperature_c": [25.0, 25.0],
            "rated_ac_power_kw": [100.0, 100.0],
            "rated_dc_power_kw": [120.0, 120.0],
            "inverter_efficiency": [0.97, 0.97],
            "system_losses_fraction": [0.0, 0.0],
            "module_temperature_coefficient_per_c": [0.0, 0.0],
        }
    )
    result = physics_baseline(frame)

    assert np.allclose(result["expected_power_kw"], 100.0)


def test_interval_based_energy_uses_actual_duration():
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                [
                    "2024-01-01T12:00:00Z",
                    "2024-01-01T12:15:00Z",
                    "2024-01-01T12:30:00Z",
                ],
                utc=True,
            ),
            "poa_irradiance_w_m2": [1000.0, 1000.0, 1000.0],
            "module_temperature_c": [25.0, 25.0, 25.0],
            "rated_ac_power_kw": [100.0, 100.0, 100.0],
            "rated_dc_power_kw": [100.0, 100.0, 100.0],
            "inverter_efficiency": [1.0, 1.0, 1.0],
            "system_losses_fraction": [0.0, 0.0, 0.0],
            "module_temperature_coefficient_per_c": [0.0, 0.0, 0.0],
        }
    )
    result = physics_baseline(frame)

    assert np.allclose(result["interval_seconds"], 900.0)
    assert np.allclose(result["expected_energy_kwh"], 25.0)


def test_benchmark_loader_excludes_ground_truth(tmp_path):
    from scripts.benchmark_expected import (
        LEAKAGE_COLUMNS,
        evaluate_frame,
        load_scenario_inputs,
    )
    from src.config import load_defaults

    scenario = tmp_path / "scenario_000"
    scenario.mkdir()
    pd.DataFrame(
        {
            "scenario_id": ["scenario_000"],
            "timestamp_utc": ["2024-01-01T12:00:00Z"],
            "inverter_id": ["INV-01"],
            "ac_power_kw": [80.0],
            "energy_kwh": [20.0],
            "module_temperature_c": [25.0],
            "ambient_temperature_c": [20.0],
            "poa_irradiance_w_m2": [800.0],
        }
    ).to_csv(scenario / "operating_data.csv", index=False)
    pd.DataFrame(
        {
            "scenario_id": ["scenario_000"],
            "timestamp_utc": ["2024-01-01T12:00:00Z"],
            "ghi_w_m2": [850.0],
            "solar_elevation_deg": [45.0],
        }
    ).to_csv(scenario / "weather.csv", index=False)
    pd.DataFrame(
        {
            "scenario_id": ["scenario_000"],
            "inverter_id": ["INV-01"],
            "rated_ac_power_kw": [100.0],
            "rated_dc_power_kw": [120.0],
            "inverter_efficiency": [0.97],
            "system_losses_fraction": [0.12],
            "module_temperature_coefficient_per_c": [-0.0035],
        }
    ).to_csv(scenario / "devices.csv", index=False)
    pd.DataFrame(
        {
            "scenario_id": ["scenario_000"],
            "fault_type": ["normal"],
            "severity": [0.0],
            "logged_in_event_log": [False],
        }
    ).to_csv(scenario / "ground_truth.csv", index=False)

    frame = load_scenario_inputs(scenario)

    assert "fault_type" not in frame.columns
    assert "severity" not in frame.columns
    assert "logged_in_event_log" not in frame.columns

    result = evaluate_frame(frame, load_defaults())
    used_columns = set(result["baseline_columns"].values())
    assert "ac_power_kw" not in used_columns
    assert "energy_kwh" not in used_columns
    assert not LEAKAGE_COLUMNS.intersection(used_columns)


def test_residual_model_returns_summary(sample_frame):
    result = residual_model(sample_frame)
    assert result["rows"] == 2
    assert "residuals" in result

