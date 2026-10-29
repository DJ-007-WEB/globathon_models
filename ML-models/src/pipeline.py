"""End-to-end pipeline orchestration for the ML-models project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .anomaly import detect_anomalies
from .attribution import explain_interval
from .baseline import physics_baseline
from .config import load_defaults
from .contract import build_contract, validate_contract, write_contract_json
from .counterfactual import Waterfall
from .schema_mapping import map_columns
from .validation import validate_frame


def _sum_energy(frame: pd.DataFrame, energy_column: str | None) -> float | None:
    if frame is None or frame.empty:
        return None
    if energy_column is not None and energy_column in frame.columns:
        values = pd.to_numeric(frame[energy_column], errors="coerce")
        return float(values.sum())
    return None


def _resolve_interval_energy(frame: pd.DataFrame, interval_minutes: float | None = None) -> float | None:
    if frame is None or frame.empty:
        return None
    if "energy_kwh" in frame.columns:
        return _sum_energy(frame, "energy_kwh")
    if "ac_power_kw" in frame.columns:
        interval_hours = (interval_minutes or 60.0) / 60.0
        values = pd.to_numeric(frame["ac_power_kw"], errors="coerce")
        return float((values * interval_hours).sum())
    return None


def _collect_interval_hypotheses(assessment_rows: pd.DataFrame, event_log: pd.DataFrame | None, config: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for _, row in assessment_rows.iterrows():
        interval = {
            "timestamp_utc": row.get("timestamp_utc"),
            "inverter_id": row.get("inverter_id"),
            "status": row.get("status"),
            "actual_power_kw": row.get("actual_power_kw"),
            "expected_power_kw": row.get("expected_power_kw"),
            "poa_irradiance_w_m2": row.get("poa_irradiance_w_m2"),
            "solar_elevation_deg": row.get("solar_elevation_deg"),
            "peer_alert": bool(row.get("peer_alert")),
            "residual_alert": bool(row.get("residual_alert")),
            "cusum_alert": bool(row.get("cusum_alert")),
            "peer_z": row.get("peer_z"),
            "peer_median": row.get("peer_median"),
            "peer_mad": row.get("peer_mad"),
            "peer_persistence": row.get("peer_persistence"),
            "alert_checks": row.get("alert_checks"),
        }
        explanation = explain_interval(interval, event_log=event_log, config=config)
        results.append(explanation)
    return results


def run_pipeline(data_path: str | Path, output_path: str | Path | None = None, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the project pipeline on a synthetic or real scenario directory.

    Stages: ingest -> map -> validate -> baseline -> anomaly -> attribution ->
    waterfall -> JSON output. The pipeline keeps physics-only fallback behavior
    and never fabricates unavailable values.
    """

    config = config or load_defaults()
    root = Path(data_path)
    if not root.exists():
        raise FileNotFoundError(f"Input data path does not exist: {root}")

    if root.is_file():
        operating = pd.read_csv(root)
        weather = None
        devices = None
        forecast = None
        event_log = None
        scenario_dir = root.parent
    else:
        scenario_dir = root
        operating = pd.read_csv(scenario_dir / "operating_data.csv") if (scenario_dir / "operating_data.csv").exists() else pd.DataFrame()
        weather = pd.read_csv(scenario_dir / "weather.csv") if (scenario_dir / "weather.csv").exists() else None
        devices = pd.read_csv(scenario_dir / "devices.csv") if (scenario_dir / "devices.csv").exists() else None
        forecast = pd.read_csv(scenario_dir / "forecast.csv") if (scenario_dir / "forecast.csv").exists() else None
        event_log = pd.read_csv(scenario_dir / "event_log.csv") if (scenario_dir / "event_log.csv").exists() else None

    if operating.empty:
        raise ValueError(f"No operating data found in input directory: {scenario_dir}")

    mapping = map_columns(operating.columns, config=config)
    validation_report = validate_frame(operating)
    base_report = physics_baseline(operating, mapping=mapping, config=config)
    anomalies = detect_anomalies(operating, weather=weather, devices=devices, mapping=mapping, config=config)
    assessments = anomalies.get("assessments", pd.DataFrame())
    interval_hypotheses = _collect_interval_hypotheses(assessments, event_log, config) if isinstance(assessments, pd.DataFrame) and not assessments.empty else []
    hypotheses = []
    for item in interval_hypotheses:
        hypotheses.extend(item.get("hypotheses", []))
    evidence = []
    for item in hypotheses:
        evidence.extend(item.get("evidence", []))
    limitations = list(base_report.get("warnings", [])) + list(anomalies.get("limitations", []))
    unresolved_fields = []
    for column_name, role in mapping.items():
        if role is None:
            unresolved_fields.append(str(column_name))

    forecast_energy = None
    if forecast is not None and "forecast_energy_kwh" in forecast.columns:
        forecast_energy = float(pd.to_numeric(forecast["forecast_energy_kwh"], errors="coerce").sum())
    if forecast_energy is None:
        forecast_energy = float(pd.to_numeric(base_report.get("expected_energy_kwh", pd.Series(dtype=float)), errors="coerce").sum()) if isinstance(base_report.get("expected_energy_kwh"), pd.Series) else None

    actual_energy = _resolve_interval_energy(operating)
    expected_energy = float(pd.to_numeric(base_report.get("expected_energy_kwh", pd.Series(dtype=float)), errors="coerce").sum()) if isinstance(base_report.get("expected_energy_kwh"), pd.Series) else None
    if expected_energy is None and actual_energy is not None:
        expected_energy = actual_energy

    if forecast_energy is None or expected_energy is None or actual_energy is None:
        waterfall_result = {
            "status": "unavailable",
            "reason": "Missing or unsupported forecast, expected, or actual energy inputs.",
            "reconciled": False,
            "forecast_energy_kwh": forecast_energy,
            "expected_energy_kwh": expected_energy,
            "actual_energy_kwh": actual_energy,
            "weather_effect_kwh": None,
            "plant_effect_kwh": None,
            "total_deviation_kwh": None,
            "observed_deviation_kwh": None,
            "estimated_anomaly_energy_kwh": None,
            "potentially_recoverable_energy_kwh": None,
        }
    else:
        waterfall_result = Waterfall.reconcile(forecast_energy, expected_energy, actual_energy)

    analysis_status = "ok" if waterfall_result.get("status") in {"ok", "warning"} else "unavailable"
    if anomalies.get("status") == "warning":
        analysis_status = "warning"

    output = build_contract(
        analysis_status,
        "Pipeline completed.",
        metrics={
            "rows": int(len(operating)),
            "alerts": len(anomalies.get("alerts", [])),
            "status": validation_report.get("valid"),
        },
        analysis_status=analysis_status,
        interval={
            "timestamp_utc": None if assessments.empty else assessments.iloc[0].get("timestamp_utc"),
            "device_id": None if assessments.empty else assessments.iloc[0].get("inverter_id"),
            "source_rows": int(len(operating)),
        },
        forecast_energy=waterfall_result.get("forecast_energy_kwh"),
        actual_energy=waterfall_result.get("actual_energy_kwh"),
        deviation=waterfall_result.get("total_deviation_kwh"),
        waterfall=waterfall_result,
        anomalies=anomalies.get("alerts", []),
        hypotheses=hypotheses,
        evidence=evidence,
        limitations=limitations,
        unresolved_fields=unresolved_fields,
        model_version="1.0.0",
        mapping_version="1.0.0",
    )
    payload = output.to_dict()
    payload["schema_version"] = "1.0.0"
    payload["analysis_status"] = analysis_status
    payload["interval"] = output.interval
    payload["forecast_energy"] = float(waterfall_result.get("forecast_energy_kwh")) if waterfall_result.get("forecast_energy_kwh") is not None else None
    payload["actual_energy"] = float(waterfall_result.get("actual_energy_kwh")) if waterfall_result.get("actual_energy_kwh") is not None else None
    payload["deviation"] = float(waterfall_result.get("total_deviation_kwh")) if waterfall_result.get("total_deviation_kwh") is not None else None
    payload["waterfall"] = waterfall_result
    payload["anomalies"] = anomalies.get("alerts", [])
    payload["hypotheses"] = hypotheses
    payload["evidence"] = evidence
    payload["limitations"] = limitations
    payload["unresolved_fields"] = unresolved_fields
    payload["model_version"] = "1.0.0"
    payload["mapping_version"] = "1.0.0"
    payload["status"] = analysis_status
    payload["message"] = "Pipeline completed."
    payload["metrics"] = {
        "rows": int(len(operating)),
        "alerts": len(anomalies.get("alerts", [])),
        "valid": bool(validation_report.get("valid", False)),
        "warnings": list(base_report.get("warnings", [])) + list(anomalies.get("limitations", [])),
    }

    validate_contract(payload)
    if output_path is not None:
        write_contract_json(payload, output_path)
    return payload


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the ML pipeline end-to-end.")
    parser.add_argument("--inputs", required=True, help="Directory containing operating_data.csv and optional weather/devices/forecast/event_log files.")
    parser.add_argument("--output", required=True, help="Output JSON path for the pipeline result.")
    args = parser.parse_args()

    payload = run_pipeline(args.inputs, args.output)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
