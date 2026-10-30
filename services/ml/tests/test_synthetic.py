from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.synthetic import (
    GROUND_TRUTH_COLUMNS,
    INPUT_COLUMN_NAMES_TO_KEEP_OUT,
    SCENARIO_KINDS,
    FaultLibrary,
    generate_batch,
    generate_synthetic_series,
    main,
)


def test_fault_library_sag_reduces_values():
    values = [100.0, 90.0, 80.0]
    reduced = FaultLibrary.sag(values, severity=1.0)
    assert reduced[0] < values[0]
    assert reduced[1] < values[1]


def test_generate_synthetic_series_uses_baseline():
    series = generate_synthetic_series(4, lambda idx: float(idx) * 10)
    assert series == [0.0, 10.0, 20.0, 30.0]


def _scenario_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir())


def test_batch_generation_is_reproducible(tmp_path):
    kwargs = {
        "seed": 123,
        "n_scenarios": 3,
        "capacity_kw": 500.0,
        "inverter_count": 2,
        "interval_minutes": 60,
        "days": 1,
        "weather": "variable",
        "sensor_noise": 0.02,
    }
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_batch(first, **kwargs)
    generate_batch(second, **kwargs)

    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(
        path.relative_to(second) for path in second.rglob("*") if path.is_file()
    )
    assert first_files == second_files
    assert first_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_physical_bounds_and_nighttime_behavior(tmp_path):
    root = tmp_path / "batch"
    generate_batch(
        root,
        seed=9,
        n_scenarios=len(SCENARIO_KINDS),
        capacity_kw=1000.0,
        inverter_count=3,
        interval_minutes=15,
        days=2,
        weather="mixed",
        sensor_noise=0.02,
    )

    night_rows = 0
    for directory in _scenario_dirs(root):
        operating = pd.read_csv(directory / "operating_data.csv")
        weather = pd.read_csv(directory / "weather.csv")
        forecast = pd.read_csv(directory / "forecast.csv")
        devices = pd.read_csv(directory / "devices.csv")

        merged = operating.merge(
            devices[["scenario_id", "inverter_id", "rated_ac_power_kw"]],
            on=["scenario_id", "inverter_id"],
            how="left",
        )
        assert (merged["rated_ac_power_kw"] > 0).all()
        assert (merged["ac_power_kw"].dropna() >= 0).all()
        assert (
            merged["ac_power_kw"].dropna()
            <= merged.loc[merged["ac_power_kw"].notna(), "rated_ac_power_kw"] + 1e-9
        ).all()
        assert (merged["dc_power_kw"].dropna() >= 0).all()
        assert (merged["energy_kwh"].dropna() >= 0).all()
        assert np.isfinite(merged["ac_power_kw"].dropna()).all()

        assert (weather["ghi_w_m2"] >= 0).all()
        assert (weather["poa_irradiance_w_m2"] >= 0).all()
        assert (weather["ghi_w_m2"] <= 1400.0 + 1e-9).all()
        assert (weather["poa_irradiance_w_m2"] <= 1400.0 + 1e-9).all()
        assert (weather["cloud_cover_fraction"] >= 0).all()
        assert (weather["cloud_cover_fraction"] <= 1).all()
        assert (weather["solar_elevation_deg"] >= -90).all()
        assert (weather["solar_elevation_deg"] <= 90).all()
        assert (forecast["forecast_ac_power_kw"] >= 0).all()
        assert (forecast["forecast_ac_power_kw"] <= 1000.0 + 1e-9).all()

        operating_night = operating.merge(
            weather[["scenario_id", "timestamp_utc", "solar_elevation_deg"]],
            on=["scenario_id", "timestamp_utc"],
            how="left",
        )
        operating_night = operating_night[
            operating_night["solar_elevation_deg"] <= 0.0
        ]
        forecast_night = forecast.merge(
            weather[["scenario_id", "timestamp_utc", "solar_elevation_deg"]],
            on=["scenario_id", "timestamp_utc"],
            how="left",
        )
        forecast_night = forecast_night[
            forecast_night["solar_elevation_deg"] <= 0.0
        ]
        night_rows += len(operating_night)
        assert (operating_night["ac_power_kw"].fillna(0.0) == 0.0).all()
        assert (operating_night["energy_kwh"].fillna(0.0) == 0.0).all()
        assert (forecast_night["forecast_ac_power_kw"].fillna(0.0) == 0.0).all()
        assert (weather.loc[weather["solar_elevation_deg"] <= 0.0, "ghi_w_m2"] == 0.0).all()

    assert night_rows > 0


def test_ground_truth_is_separate_and_faults_are_covered(tmp_path):
    root = tmp_path / "batch"
    generate_batch(
        root,
        seed=21,
        n_scenarios=len(SCENARIO_KINDS),
        capacity_kw=1000.0,
        inverter_count=3,
        interval_minutes=30,
        days=2,
        weather="mixed",
    )

    ground_truth = pd.concat(
        [pd.read_csv(directory / "ground_truth.csv") for directory in _scenario_dirs(root)],
        ignore_index=True,
    )
    assert list(ground_truth.columns) == list(GROUND_TRUTH_COLUMNS)
    assert set(SCENARIO_KINDS) <= set(ground_truth["fault_type"])

    for directory in _scenario_dirs(root):
        for filename in [
            "operating_data.csv",
            "weather.csv",
            "forecast.csv",
            "devices.csv",
            "event_log.csv",
        ]:
            columns = set(pd.read_csv(directory / filename).columns)
            assert not (columns & INPUT_COLUMN_NAMES_TO_KEEP_OUT)
            assert "ground_truth" not in columns

        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["synthetic"] is True
        assert "fault_type" not in metadata
        assert "ground_truth" not in json.dumps(metadata)


def test_missing_and_communication_gaps_are_nan(tmp_path):
    root = tmp_path / "batch"
    generate_batch(
        root,
        seed=33,
        n_scenarios=len(SCENARIO_KINDS),
        capacity_kw=500.0,
        inverter_count=2,
        interval_minutes=60,
        days=1,
        weather="clear",
    )

    communication_checked = False
    missing_checked = False
    for directory in _scenario_dirs(root):
        ground_truth = pd.read_csv(directory / "ground_truth.csv")
        operating = pd.read_csv(directory / "operating_data.csv")
        for _, event in ground_truth.iterrows():
            if event["fault_type"] == "communication_gap":
                rows = operating[
                    (operating["inverter_id"] == event["asset_id"])
                    & (operating["timestamp_utc"] >= event["start_utc"])
                    & (operating["timestamp_utc"] <= event["end_utc"])
                ]
                numeric = [
                    "ac_power_kw",
                    "dc_power_kw",
                    "energy_kwh",
                    "module_temperature_c",
                    "ambient_temperature_c",
                    "poa_irradiance_w_m2",
                ]
                assert not rows.empty
                assert rows[numeric].isna().all().all()
                communication_checked = True
            if event["fault_type"] == "missing_readings":
                assert operating.isna().sum().sum() > 0
                missing_checked = True

    assert communication_checked
    assert missing_checked


def test_cli_accepts_required_options(tmp_path):
    out = tmp_path / "cli_batch"
    result = main(
        [
            "--seed",
            "5",
            "--n-scenarios",
            "1",
            "--out",
            str(out),
            "--capacity-kw",
            "100",
            "--inverters",
            "1",
            "--interval-minutes",
            "60",
            "--days",
            "1",
        ]
    )
    assert result == 0
    assert (out / "manifest.json").is_file()
    assert (out / "scenario_000" / "ground_truth.csv").is_file()
