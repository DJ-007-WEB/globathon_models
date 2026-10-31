"""End-to-end integration tests for the contract-v2 analysis boundary."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.contract import validate_contract
from src.service import analyze
from src.synthetic import generate_batch


def _assert_contract(result: dict) -> None:
    validate_contract(result)
    assert result["schema_version"] == "2.1.0"
    assert result["analysis_status"] in {"success", "partial", "invalid_input", "failed"}
    assert result["analysis_mode"] in {"snapshot", "full"}
    assert set(result["energy"]) == {"forecast", "expected", "actual", "deviation"}
    assert set(result["capabilities"]) >= {
        "basic_validation",
        "baseline",
        "persistence",
        "peer_comparison",
        "trend_analysis",
        "event_correlation",
        "energy_waterfall",
    }


def _power_frame(periods: int = 4, freq: str = "15min") -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=periods, freq=freq)
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": "INV-A",
            "ac_power_kw": 100.0,
            "poa_irradiance_w_m2": 1000.0,
            "ambient_temperature_c": 25.0,
            "module_temperature_c": 45.0,
            "rated_ac_power_kw": 100.0,
            "rated_dc_power_kw": 120.0,
            "inverter_efficiency": 0.97,
            "system_losses_fraction": 0.12,
        }
    )


def _operating_frame(periods: int = 3, freq: str = "1h") -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=periods, freq=freq)
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": "INV-A",
            "ac_power_kw": 80.0,
            "energy_kwh": 80.0,
            "poa_irradiance_w_m2": 1000.0,
            "ambient_temperature_c": 25.0,
            "module_temperature_c": 45.0,
            "rated_ac_power_kw": 100.0,
            "rated_dc_power_kw": 120.0,
            "inverter_efficiency": 0.97,
            "system_losses_fraction": 0.12,
        }
    )


def test_t01_full_end_to_end_analysis(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    generate_batch(
        batch,
        seed=7,
        n_scenarios=1,
        days=1,
        interval_minutes=60,
        capacity_kw=500.0,
    )
    result = analyze(batch / "scenario_000")

    _assert_contract(result)
    assert result["analysis_status"] == "success"
    assert result["analysis_mode"] == "full"
    assert result["actual_energy"] is not None
    assert result["expected_energy"] is not None
    assert result["forecast_energy"] is not None
    assert result["waterfall"]["status"] == "ok"
    assert result["waterfall"]["reconciled"] is True
    assert result["interval"]["row_count"] > 0
    assert result["data_quality"]["rows"] > 0


def test_t02_energy_is_derived_from_actual_interval_duration() -> None:
    result = analyze(
        {
            "operating_data": _power_frame(periods=4, freq="15min"),
            "forecast_data": pd.DataFrame(
                {
                    "timestamp_utc": pd.date_range(
                        "2024-01-01T10:00:00Z", periods=4, freq="15min"
                    ),
                    "forecast_ac_power_kw": 100.0,
                }
            ),
        }
    )

    _assert_contract(result)
    assert result["analysis_status"] == "success"
    assert result["interval"]["sampling_interval_seconds"] == 900.0
    assert result["actual_energy"] == pytest.approx(100.0)
    assert result["forecast_energy"] == pytest.approx(100.0)
    assert "actual_interval_duration" in result["energy"]["actual"]["source"]
    assert "actual_interval_duration" in result["energy"]["forecast"]["source"]
    assert result["actual_energy"] != pytest.approx(400.0)


def test_t03_alias_mapping_and_canonical_columns() -> None:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=3, freq="1h")
    operating = pd.DataFrame(
        {
            "Time": timestamps,
            "Inverter": "INV-A",
            "AC Power (kW)": 80.0,
            "POA (W/m2)": 1000.0,
            "Ambient Temp (C)": 25.0,
            "Module Temp (C)": 45.0,
            "Rated Capacity (kW)": 100.0,
        }
    )
    forecast = pd.DataFrame({"Time": timestamps, "Forecast Energy (kWh)": 80.0})

    result = analyze({"operating_data": operating, "forecast_data": forecast})

    _assert_contract(result)
    assert result["analysis_status"] == "success"
    assert result["unresolved_fields"] == []
    assert result["missing_required_fields"] == []
    assert result["actual_energy"] == pytest.approx(240.0)
    assert result["forecast_energy"] == pytest.approx(240.0)
    assert result["expected_energy"] is not None


def test_t04_missing_measurements_are_null_not_zero() -> None:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=3, freq="1h")
    operating = pd.DataFrame({"timestamp_utc": timestamps, "inverter_id": "INV-A"})

    result = analyze(operating)

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert result["actual_energy"] is None
    assert result["expected_energy"] is None
    assert result["forecast_energy"] is None
    assert result["energy"]["actual"]["value_kwh"] is None
    assert result["energy"]["expected"]["value_kwh"] is None
    assert result["waterfall"]["status"] == "unavailable"
    assert {"power_ac", "energy_interval", "irradiance_poa", "capacity"} <= set(
        result["missing_required_fields"]
    )


def test_t05_time_gaps_are_reported_and_analysis_is_partial() -> None:
    timestamps = pd.to_datetime(
        [
            "2024-01-01T10:00:00Z",
            "2024-01-01T11:00:00Z",
            "2024-01-01T13:00:00Z",
        ]
    )
    operating = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": "INV-A",
            "energy_kwh": [10.0, 11.0, 13.0],
            "ac_power_kw": [10.0, 11.0, 13.0],
            "poa_irradiance_w_m2": [500.0, 600.0, 700.0],
            "rated_ac_power_kw": [100.0] * 3,
        }
    )

    result = analyze(operating)

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert result["data_quality"]["status"] == "warning"
    gaps = next(
        check
        for check in result["data_quality"]["checks"]
        if check["check_id"] == "time_gaps"
    )
    assert gaps["status"] == "warning"
    assert gaps["count"] >= 1
    assert result["actual_energy"] == pytest.approx(34.0)


def test_t06_duplicate_and_out_of_order_timestamps_are_reported() -> None:
    timestamps = pd.to_datetime(
        [
            "2024-01-01T11:00:00Z",
            "2024-01-01T10:00:00Z",
            "2024-01-01T10:00:00Z",
        ]
    )
    operating = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": "INV-A",
            "energy_kwh": [10.0, 11.0, 12.0],
            "ac_power_kw": [10.0, 11.0, 12.0],
            "poa_irradiance_w_m2": [500.0, 600.0, 700.0],
            "rated_ac_power_kw": [100.0] * 3,
        }
    )

    result = analyze(operating)

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert result["data_quality"]["status"] == "fail"
    checks = {check["check_id"]: check for check in result["data_quality"]["checks"]}
    assert checks["duplicate_timestamps"]["status"] == "fail"
    assert checks["out_of_order_timestamps"]["status"] == "fail"


def test_t07_unit_conversion_is_explicit() -> None:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=4, freq="1h")
    operating = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": "INV-A",
            "ac_power_w": 80000.0,
            "energy_wh": 80000.0,
            "poa_irradiance_kw_m2": 1.0,
            "ambient_temperature_c": 25.0,
            "module_temperature_c": 45.0,
            "rated_capacity_kw": 100.0,
        }
    )
    forecast = pd.DataFrame(
        {"timestamp_utc": timestamps, "forecast_energy_wh": 80000.0}
    )

    result = analyze({"operating_data": operating, "forecast_data": forecast})

    _assert_contract(result)
    assert result["analysis_status"] == "success"
    assert result["interval"]["sampling_interval_seconds"] == 3600.0
    assert result["actual_energy"] == pytest.approx(320.0)
    assert result["forecast_energy"] == pytest.approx(320.0)
    assert result["expected_energy"] is not None
    assert result["unresolved_fields"] == []
    assert result["data_quality"]["status"] == "pass"


def test_t08_snapshot_mode_does_not_claim_time_series_evidence() -> None:
    operating = _operating_frame(periods=1)
    forecast = pd.DataFrame(
        {
            "timestamp_utc": operating["timestamp_utc"],
            "forecast_energy_kwh": 80.0,
        }
    )

    result = analyze({"operating_data": operating, "forecast_data": forecast})

    _assert_contract(result)
    assert result["analysis_mode"] == "snapshot"
    assert result["analysis_status"] == "partial"
    assert result["capabilities"]["persistence"]["status"] == "not_applicable"
    assert result["capabilities"]["peer_comparison"]["status"] == "not_applicable"
    assert result["capabilities"]["trend_analysis"]["status"] == "not_applicable"
    assert result["anomalies"] == []
    assert result["hypotheses"] == []
    assert result["actual_energy"] == pytest.approx(80.0)
    assert result["forecast_energy"] == pytest.approx(80.0)
    assert result["expected_energy"] is None
    assert result["waterfall"]["status"] == "unavailable"


def test_t09_logged_outage_is_not_confirmed_when_output_is_not_low() -> None:
    timestamps = pd.date_range("2024-01-01T10:00:00Z", periods=3, freq="1h")
    rows = []
    for timestamp in timestamps:
        for device, ac_power in (("INV-A", 90.0), ("INV-B", 100.0), ("INV-C", 100.0)):
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "inverter_id": device,
                    "ac_power_kw": ac_power,
                    "energy_kwh": ac_power,
                    "poa_irradiance_w_m2": 1000.0,
                    "ambient_temperature_c": 25.0,
                    "module_temperature_c": 45.0,
                    "rated_ac_power_kw": 100.0,
                    "rated_dc_power_kw": 120.0,
                    "inverter_efficiency": 0.97,
                    "system_losses_fraction": 0.12,
                }
            )
    operating = pd.DataFrame(rows)
    forecast = pd.DataFrame(
        {"timestamp_utc": timestamps, "forecast_energy_kwh": 300.0}
    )
    events = pd.DataFrame(
        {
            "start_utc": [timestamps[0]],
            "end_utc": [timestamps[-1]],
            "event_type": ["grid_outage"],
            "asset_id": ["INV-A"],
            "description": ["logged outage"],
        }
    )

    result = analyze(
        {
            "operating_data": operating,
            "forecast_data": forecast,
            "event_log": events,
        }
    )

    _assert_contract(result)
    assert result["anomalies"]
    outage_hypotheses = [
        hypothesis
        for hypothesis in result["hypotheses"]
        if hypothesis["cause"] == "logged_outage_or_curtailment"
    ]
    assert outage_hypotheses
    assert all(
        hypothesis["status"] == "unresolved"
        and hypothesis["root_cause_confirmed"] is False
        for hypothesis in outage_hypotheses
    )
    assert any("event alone" in limitation for limitation in result["limitations"])


def test_t10_missing_forecast_stays_null_and_marks_analysis_partial() -> None:
    result = analyze(_operating_frame(periods=3))

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert result["forecast_energy"] is None
    assert result["energy"]["forecast"]["status"] == "unavailable"
    assert result["actual_energy"] is not None
    assert result["expected_energy"] is not None
    assert result["waterfall"]["status"] == "unavailable"


def test_t11_missing_actual_measurements_are_explicit() -> None:
    operating = _operating_frame(periods=3).drop(columns=["ac_power_kw", "energy_kwh"])
    forecast = pd.DataFrame(
        {
            "timestamp_utc": operating["timestamp_utc"],
            "forecast_energy_kwh": 80.0,
        }
    )

    result = analyze({"operating_data": operating, "forecast_data": forecast})

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert result["actual_energy"] is None
    assert result["energy"]["actual"]["status"] == "unavailable"
    assert result["expected_energy"] is not None
    assert result["forecast_energy"] is not None
    assert result["waterfall"]["status"] == "unavailable"
    assert {"power_ac", "energy_interval"} <= set(result["missing_required_fields"])


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("empty", "EMPTY_FILE"),
        ("unsupported", "UNSUPPORTED_FILE_TYPE"),
        ("missing", "INPUT_NOT_FOUND"),
        ("missing_operating", "MISSING_OPERATING_DATA"),
    ],
)
def test_t12_structured_input_errors(
    tmp_path: Path, kind: str, expected_code: str
) -> None:
    if kind == "empty":
        source = tmp_path / "empty.csv"
        source.write_text("", encoding="utf-8")
    elif kind == "unsupported":
        source = tmp_path / "input.txt"
        source.write_text("not tabular", encoding="utf-8")
    elif kind == "missing":
        source = tmp_path / "does_not_exist.csv"
    else:
        source = tmp_path / "scenario"
        source.mkdir()
        (source / "weather.csv").write_text(
            "timestamp_utc,poa_irradiance_w_m2\n2024-01-01T10:00:00Z,500\n",
            encoding="utf-8",
        )

    result = analyze(source)

    _assert_contract(result)
    assert result["analysis_status"] == "invalid_input"
    assert result["errors"]
    assert result["errors"][0]["code"] == expected_code
    assert result["actual_energy"] is None
    assert result["waterfall"]["status"] == "unavailable"


def test_t12_ambiguous_timestamp_is_a_structured_nonfatal_error() -> None:
    operating = pd.DataFrame(
        {
            "timestamp": ["01/02/2024 10:00", "01/02/2024 11:00"],
            "inverter_id": ["INV-A", "INV-A"],
            "energy_kwh": [10.0, 11.0],
            "poa_irradiance_w_m2": [500.0, 600.0],
            "rated_ac_power_kw": [100.0, 100.0],
        }
    )

    result = analyze(operating)

    _assert_contract(result)
    assert result["analysis_status"] == "partial"
    assert any(error["code"] == "AMBIGUOUS_TIMESTAMP" for error in result["errors"])
    assert result["interval"]["timestamp_basis"] in {"local", "unresolved"}
