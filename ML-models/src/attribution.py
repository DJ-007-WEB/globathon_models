"""Interpretable, evidence-based attribution rules.

Attribution does not prove a physical root cause.  It reports which hypotheses
are supported, which are only logged events, and what evidence is still missing.
An event-log entry is treated as a confirmed event only when interval behavior is
also consistent with it; a log entry alone remains unresolved for causation.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import get_path, json_safe, load_defaults

CONFIRMED_EVENT = "confirmed_event"
SUSPECTED = "suspected"
UNRESOLVED = "unresolved"

DATA_COMMUNICATION = "data_or_communication_issue"
LOGGED_OUTAGE = "logged_outage_or_curtailment"
LOW_OUTPUT = "low_output_under_adequate_irradiance"
PEER_UNDERPERFORMANCE = "peer_underperformance"
SENSOR_ISSUE = "sensor_issue"
UNRESOLVED_CAUSE = "unresolved"

CAUSE_LABELS = {
    DATA_COMMUNICATION: "Data or communication issue",
    LOGGED_OUTAGE: "Logged outage or curtailment",
    LOW_OUTPUT: "Low output under adequate irradiance",
    PEER_UNDERPERFORMANCE: "Peer underperformance",
    SENSOR_ISSUE: "Sensor issue",
    UNRESOLVED_CAUSE: "Unresolved",
}

PRIORITY = {
    DATA_COMMUNICATION: 0,
    LOGGED_OUTAGE: 1,
    SENSOR_ISSUE: 2,
    PEER_UNDERPERFORMANCE: 3,
    LOW_OUTPUT: 4,
    UNRESOLVED_CAUSE: 9,
}


def _record(interval: Any) -> dict[str, Any]:
    if isinstance(interval, pd.Series):
        record = interval.to_dict()
    elif isinstance(interval, Mapping):
        record = dict(interval)
    else:
        record = {"value": interval}
    evidence = record.get("evidence")
    if isinstance(evidence, Mapping):
        for key, value in evidence.items():
            record.setdefault(key, value)
    return record


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _number(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value = _first(record, keys)
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _interval_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_utc": json_safe(_first(record, ("timestamp_utc", "timestamp", "start_utc"))),
        "device_id": _first(record, ("inverter_id", "device_id", "asset_id")),
    }


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed


def _event_frame(event_log: Any) -> pd.DataFrame:
    if event_log is None:
        return pd.DataFrame()
    if isinstance(event_log, pd.DataFrame):
        return event_log.copy()
    try:
        return pd.DataFrame(event_log)
    except (TypeError, ValueError):
        return pd.DataFrame()


def _event_kind(event_type: Any) -> str:
    text = str(event_type or "").lower()
    if "curtail" in text or "outage" in text or "load_shed" in text:
        return "outage_curtailment"
    if "communication" in text or "telemetry" in text or "missing" in text:
        return "data_communication"
    if "sensor" in text:
        return "sensor"
    if "maintenance" in text:
        return "maintenance"
    return "other"


def _overlapping_events(
    event_log: Any,
    timestamp: Any,
    device: Any,
) -> list[dict[str, Any]]:
    frame = _event_frame(event_log)
    if frame.empty or timestamp is None:
        return []
    timestamp_value = _timestamp(timestamp)
    if timestamp_value is None or "start_utc" not in frame.columns or "end_utc" not in frame.columns:
        return []
    starts = pd.to_datetime(frame["start_utc"], errors="coerce", utc=True)
    ends = pd.to_datetime(frame["end_utc"], errors="coerce", utc=True)
    assets = frame["asset_id"].astype(str) if "asset_id" in frame.columns else pd.Series("", index=frame.index)
    event_types = frame["event_type"].astype(str) if "event_type" in frame.columns else pd.Series("", index=frame.index)
    device_text = str(device) if device is not None else ""
    asset_match = assets.map(
        lambda value: value in {"PLANT", "PLANT-WIDE", device_text}
        or "sensor" in value.lower()
        or value == ""
    )
    type_match = event_types.map(lambda value: "sensor" in value.lower())
    mask = (starts <= timestamp_value) & (ends >= timestamp_value) & (asset_match | type_match)
    return [row._asdict() for row in frame.loc[mask].itertuples(index=False)]


def _event_text(event: Mapping[str, Any]) -> str:
    event_type = event.get("event_type", "event")
    asset = event.get("asset_id", "unknown asset")
    start = event.get("start_utc", "?")
    end = event.get("end_utc", "?")
    return f"event_log: event_type={event_type}, asset_id={asset}, start={start}, end={end}"


def _hypothesis(
    cause: str,
    status: str,
    interval: dict[str, Any],
    evidence: list[str],
    missing_evidence: list[str],
    *,
    primary_allowed: bool,
    confidence: float,
) -> dict[str, Any]:
    return {
        "cause": cause,
        "label": CAUSE_LABELS[cause],
        "status": status,
        "root_cause_confirmed": False,
        "event_confirmed": status == CONFIRMED_EVENT,
        "primary_allowed": primary_allowed,
        "confidence": confidence,
        "interval": interval,
        "evidence": evidence,
        "missing_evidence": missing_evidence,
        "source": "deterministic_rule",
    }


def _confidence(status: str) -> float:
    return {CONFIRMED_EVENT: 0.85, SUSPECTED: 0.60, UNRESOLVED: 0.15}.get(status, 0.15)


def explain_interval(
    interval: Any,
    *,
    event_log: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return evidence-based hypotheses for one interval/device.

    The result has at most one ``primary_cause``.  Any other supported
    hypotheses are retained in ``secondary_hypotheses``; all are in ``causes``.
    """

    config = config or load_defaults()
    record = _record(interval)
    summary = _interval_summary(record)
    actual = _number(record, ("actual_power_kw", "ac_power_kw", "actual", "power"))
    expected = _number(record, ("expected_power_kw", "expected_ac_power_kw", "expected"))
    poa = _number(record, ("poa_irradiance_w_m2", "irradiance_poa", "poa"))
    sun = _number(record, ("solar_elevation_deg", "sun_elevation_deg"))
    status = str(record.get("status") or "")
    checks = record.get("alert_checks") or record.get("checks") or []
    if isinstance(checks, str):
        checks = [checks]
    checks = {str(item) for item in checks}
    peer_alert = bool(record.get("peer_alert")) or "peer_output_deviation" in checks
    peer_z = _number(record, ("peer_z", "peer_score"))
    peer_median = _number(record, ("peer_median", "peer_average"))
    peer_mad = _number(record, ("peer_mad", "peer_dispersion"))
    peer_persistence = _number(record, ("peer_persistence", "persistence"))
    peer_below = peer_alert and (peer_z is None or peer_z < 0.0)

    events = _overlapping_events(event_log, summary["timestamp_utc"], summary["device_id"])
    outage_events = [event for event in events if _event_kind(event.get("event_type")) == "outage_curtailment"]
    communication_events = [event for event in events if _event_kind(event.get("event_type")) == "data_communication"]
    sensor_events = [event for event in events if _event_kind(event.get("event_type")) == "sensor"]

    low_ratio = float(get_path(config, "attribution.low_output_ratio", 0.80))
    adequate_irradiance = float(
        get_path(config, "attribution.adequate_irradiance_w_m2", 50.0)
    )
    night_threshold = float(
        get_path(config, "attribution.night_sun_elevation_deg", -0.833)
    )
    min_expected = float(get_path(config, "attribution.min_expected_power_kw", 0.5))
    daytime = sun is None or sun > night_threshold
    adequate = poa is not None and poa >= adequate_irradiance and daytime
    ratio = actual / expected if actual is not None and expected is not None and expected > 0 else None
    low_output = bool(
        adequate
        and expected is not None
        and expected >= min_expected
        and ratio is not None
        and ratio < low_ratio
    )

    missing_reasons: list[str] = []
    if actual is None:
        missing_reasons.append("actual power is missing")
    if expected is None:
        missing_reasons.append("expected power is missing")
    if poa is None:
        missing_reasons.append("irradiance is missing")
    if status == "unavailable" and not missing_reasons:
        missing_reasons.append("assessment marked unavailable")
    sensor_evidence = poa is None or "sensor_issue" in checks or bool(record.get("sensor_issue"))

    hypotheses: list[dict[str, Any]] = []
    missing_general = [
        "cause-specific evidence such as device status, diagnostics, or inspection"
    ]

    if missing_reasons:
        confirmed = bool(communication_events)
        evidence = [f"missing interval readings: {', '.join(missing_reasons)}"]
        evidence.extend(_event_text(event) for event in communication_events)
        hypotheses.append(
            _hypothesis(
                DATA_COMMUNICATION,
                CONFIRMED_EVENT if confirmed else SUSPECTED,
                summary,
                evidence,
                [
                    "complete telemetry for the interval",
                    "root cause of the data or communication loss",
                ],
                primary_allowed=True,
                confidence=_confidence(CONFIRMED_EVENT if confirmed else SUSPECTED),
            )
        )
    elif communication_events:
        hypotheses.append(
            _hypothesis(
                DATA_COMMUNICATION,
                UNRESOLVED,
                summary,
                [_event_text(event) for event in communication_events],
                ["observed missing or unavailable readings during the logged communication event"],
                primary_allowed=False,
                confidence=_confidence(UNRESOLVED),
            )
        )

    if outage_events:
        event_evidence = [_event_text(event) for event in outage_events]
        if low_output:
            event_evidence.append(
                f"observed output ratio {ratio:.3f} is below {low_ratio:.3f}"
            )
            hypotheses.append(
                _hypothesis(
                    LOGGED_OUTAGE,
                    CONFIRMED_EVENT,
                    summary,
                    event_evidence,
                    ["physical root-cause confirmation from device diagnostics or inspection"],
                    primary_allowed=True,
                    confidence=_confidence(CONFIRMED_EVENT),
                )
            )
        else:
            hypotheses.append(
                _hypothesis(
                    LOGGED_OUTAGE,
                    UNRESOLVED,
                    summary,
                    event_evidence,
                    ["observed output loss consistent with the logged event"],
                    primary_allowed=False,
                    confidence=_confidence(UNRESOLVED),
                )
            )

    if sensor_events or sensor_evidence:
        evidence = [_event_text(event) for event in sensor_events]
        if poa is None:
            evidence.append("POA irradiance is unavailable for the interval")
        if "sensor_issue" in checks:
            evidence.append("anomaly check indicates a sensor-related data issue")
        sensor_status = (
            CONFIRMED_EVENT if sensor_events and sensor_evidence else SUSPECTED if sensor_evidence else UNRESOLVED
        )
        hypotheses.append(
            _hypothesis(
                SENSOR_ISSUE,
                sensor_status,
                summary,
                evidence or ["irradiance behavior is inconsistent with other evidence"],
                ["sensor calibration, maintenance record, or replacement evidence"],
                primary_allowed=sensor_status != UNRESOLVED,
                confidence=_confidence(sensor_status),
            )
        )

    if peer_below:
        evidence = ["output is below the median of comparable peer devices"]
        if peer_median is not None:
            evidence.append(f"peer median normalized output={peer_median:.3f}")
        if peer_mad is not None:
            evidence.append(f"peer MAD={peer_mad:.3f}")
        if peer_z is not None:
            evidence.append(f"robust peer score={peer_z:.3f}")
        if peer_persistence is not None:
            evidence.append(f"persistence={int(peer_persistence)} intervals")
        hypotheses.append(
            _hypothesis(
                PEER_UNDERPERFORMANCE,
                SUSPECTED,
                summary,
                evidence,
                ["device-level cause evidence such as outage, derating, or inspection"],
                primary_allowed=True,
                confidence=_confidence(SUSPECTED),
            )
        )

    if low_output:
        evidence = [
            f"output ratio {ratio:.3f} is below the configured {low_ratio:.3f} threshold",
            f"POA irradiance {poa:.1f} W/m2 is adequate for assessment",
        ]
        if expected is not None and expected >= min_expected:
            evidence.append(f"physics-expected output={expected:.3f} kW")
        hypotheses.append(
            _hypothesis(
                LOW_OUTPUT,
                SUSPECTED,
                summary,
                evidence,
                ["root-cause evidence such as a logged event, device fault, or inspection"],
                primary_allowed=True,
                confidence=_confidence(SUSPECTED),
            )
        )

    candidates = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis["primary_allowed"] and hypothesis["status"] in {CONFIRMED_EVENT, SUSPECTED}
    ]
    primary = min(candidates, key=lambda item: PRIORITY[item["cause"]]) if candidates else None
    if primary is None:
        evidence = []
        if events:
            evidence.append("event-log entries overlap the interval")
        if not evidence:
            evidence.append("no specific rule produced enough evidence")
        hypotheses.append(
            _hypothesis(
                UNRESOLVED_CAUSE,
                UNRESOLVED,
                summary,
                evidence,
                [
                    "a confirmed event or physical root cause",
                    "complete interval telemetry and device diagnostics",
                ],
                primary_allowed=False,
                confidence=_confidence(UNRESOLVED),
            )
        )

    secondary = [hypothesis for hypothesis in hypotheses if hypothesis is not primary]
    top_status = primary["status"] if primary is not None else UNRESOLVED
    confidence = primary["confidence"] if primary is not None else _confidence(UNRESOLVED)
    notes: list[str] = []
    if outage_events and not low_output:
        notes.append("A logged event alone does not establish causation for this interval.")
    if status in {"suppressed_low_irradiance", "suppressed_night"}:
        notes.append("Low-irradiance or nighttime suppression prevented a low-output alert.")
    if sensor_events and not sensor_evidence:
        notes.append("A logged sensor event alone does not establish root cause.")

    return {
        "interval": summary,
        "status": top_status,
        "root_cause_confirmed": False,
        "primary_cause": primary["cause"] if primary is not None else None,
        "primary_hypothesis": primary,
        "secondary_hypotheses": secondary,
        # Backward-compatible name used by the original placeholder.
        "causes": hypotheses,
        "hypotheses": hypotheses,
        "confidence": confidence,
        "notes": notes,
        "limitations": [
            "Attribution is rule-based and cannot confirm a physical root cause by itself.",
            "Logged events confirm only the logged event, not the physical mechanism.",
        ],
    }


def attribute_alerts(
    alerts: list[Any],
    *,
    event_log: Any | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Explain a sequence of alert/assessment records with the same rules."""

    return [
        explain_interval(alert, event_log=event_log, config=config)
        for alert in alerts
    ]
