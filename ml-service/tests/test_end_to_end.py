import pytest

from src.pipeline import run_pipeline
from src.synthetic import generate_batch


def test_pipeline_smoke(tmp_path):
    input_dir = tmp_path / "scenario"
    output_path = tmp_path / "result.json"

    generate_batch(input_dir, seed=7, n_scenarios=1, days=1, interval_minutes=60, capacity_kw=500.0)
    result = run_pipeline(input_dir / "scenario_000", output_path=output_path)

    assert result["schema_version"] == "2.0.0"
    assert result["analysis_status"] in {"success", "partial"}
    assert output_path.exists()
    assert result["waterfall"]["status"] in {"ok", "warning", "unavailable"}
    assert result["interval"]["row_count"] > 0
    assert result["data_quality"]["rows"] > 0

def test_enriched_four_inverter_csv_runs_through_full_operating_pipeline(tmp_path):
    import pandas as pd

    from src.service import analyze

    path = tmp_path / "solar_enriched.csv"
    rows = []
    records = [
        ("06:45:00Z", "INV-01", 2.215613, 2.284137, 0.553903, 16.979303, 17.235296, 2.677635),
        ("06:45:00Z", "INV-02", 2.220198, 2.288864, 0.555050, 16.979303, 17.235296, 2.677635),
        ("06:45:00Z", "INV-03", 2.200000, 2.268041, 0.550000, 16.979303, 17.235296, 2.677635),
        ("06:45:00Z", "INV-04", 2.230000, 2.299072, 0.557500, 16.979303, 17.235296, 2.677635),
        ("07:00:00Z", "INV-01", 5.061777, 5.218327, 1.265444, 38.878586, 38.488676, 5.497980),
        ("07:00:00Z", "INV-02", 5.079037, 5.236121, 1.269759, 38.878586, 38.488676, 5.497980),
        ("07:00:00Z", "INV-03", 5.050000, 5.206186, 1.262500, 38.878586, 38.488676, 5.497980),
        ("07:00:00Z", "INV-04", 5.040000, 5.195876, 1.260000, 38.878586, 38.488676, 5.497980),
    ]
    for time, inverter, ac, dc, energy, poa, ghi, elevation in records:
        rows.append({
            "scenario_id": "scenario_000",
            "synthetic": True,
            "timestamp_utc": f"2024-01-01T{time}",
            "inverter_id": inverter,
            "ac_power_kw": ac,
            "dc_power_kw": dc,
            "energy_kwh": energy,
            "module_temperature_c": 17.0,
            "ambient_temperature_c": 16.0,
            "poa_irradiance_w_m2": poa,
            "rated_ac_power_kw": 125.0,
            "rated_dc_power_kw": 150.0,
            "inverter_efficiency": 0.97,
            "dc_ac_ratio": 1.2,
            "module_temperature_coefficient_per_c": -0.0035,
            "system_losses_fraction": 0.12,
            "latitude_deg": 30.090742,
            "longitude_deg": 7.388604,
            "solar_elevation_deg": elevation,
            "ghi_w_m2": ghi,
            "dni_w_m2": 0.0,
            "dhi_w_m2": 17.22596,
            "cloud_cover_fraction": 0.64,
        })
    pd.DataFrame(rows).to_csv(path, index=False)

    result = analyze(path, mode="full")

    assert result["analysis_mode"] == "full"
    assert result["analysis_status"] in {"success", "partial"}
    assert result["interval"]["device_count"] == 4
    assert result["interval"]["row_count"] == 8
    assert result["interval"]["sampling_interval_seconds"] == 900.0
    assert result["actual_energy"] == pytest.approx(
        sum(row[4] for row in records), abs=1e-6
    )
    assert result["expected_energy"] is not None
    assert result["unresolved_fields"] == []
