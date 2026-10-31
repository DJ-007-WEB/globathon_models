"""Deterministic anomaly detection for expected-output residuals and peers.

The detector never fills missing readings with zero.  A reading that is absent,
or a timestamp gap, is marked ``unavailable`` and is not scored.  Peer checks
run only at timestamps where enough devices have comparable rated capacities and
adequate irradiance.  Alerts describe observed behavior, not its cause.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .baseline import physics_baseline
from .config import get_path, json_safe, load_defaults

ACTUAL_CANDIDATES = ("ac_power_kw", "power_ac", "ac_power", "power")
EXPECTED_CANDIDATES = ("expected_power_kw", "expected_ac_power_kw", "baseline_power_kw")
DEVICE_CANDIDATES = ("inverter_id", "device_id", "asset_id")
TIMESTAMP_CANDIDATES = ("timestamp_utc", "timestamp", "__timestamp_utc__", "__timestamp_local__")
POA_CANDIDATES = ("poa_irradiance_w_m2", "irradiance_poa", "poa_w_m2", "poa")
GHI_CANDIDATES = ("ghi_w_m2", "irradiance_ghi", "ghi")
SUN_CANDIDATES = ("solar_elevation_deg", "sun_elevation_deg")
CAPACITY_CANDIDATES = ("rated_ac_power_kw", "capacity_kw", "ac_capacity_kw", "rated_capacity_kw", "capacity")
DC_CAPACITY_CANDIDATES = ("rated_dc_power_kw", "dc_capacity_kw", "rated_dc_kw")
EFFICIENCY_CANDIDATES = ("inverter_efficiency", "efficiency")
LOSSES_CANDIDATES = ("system_losses_fraction", "system_losses", "losses_fraction")
GAMMA_CANDIDATES = ("module_temperature_coefficient_per_c", "temperature_coefficient_per_c", "gamma")
MODULE_TEMP_CANDIDATES = ("module_temperature_c", "module_temp_c", "module_temperature")
AMBIENT_TEMP_CANDIDATES = ("ambient_temperature_c", "ambient_temp_c", "ambient_temperature")


def _mapping_lookup(mapping: Any | None) -> dict[str, str]:
    if mapping is None:
        return {}
    fields = getattr(mapping, "fields", None)
    if fields is None and isinstance(mapping, Mapping):
        fields = mapping.get("fields", [])
    columns: dict[str, str] = {}
    for field in fields or []:
        role = field.get("canonical_role")
        column = field.get("internal_column")
        if role and column and not field.get("unresolved") and role not in columns:
            columns[str(role)] = str(column)
    return columns


def _find(
    frame: pd.DataFrame,
    explicit: str | None,
    candidates: tuple[str, ...],
    role: str,
    mapping_columns: dict[str, str],
) -> str | None:
    if explicit:
        return explicit if explicit in frame.columns else None
    mapped = mapping_columns.get(role)
    if mapped and mapped in frame.columns:
        return mapped
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None or column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _merge_missing_columns(
    frame: pd.DataFrame,
    extra: pd.DataFrame | None,
    keys: list[str],
    wanted: tuple[str, ...],
) -> pd.DataFrame:
    if extra is None or extra.empty or not keys or not all(key in extra.columns for key in keys):
        return frame
    if not all(key in frame.columns for key in keys):
        return frame
    columns = [key for key in keys]
    columns.extend(
        column
        for column in wanted
        if column in extra.columns and column not in frame.columns
    )
    if len(columns) == len(keys):
        return frame
    selected = extra[columns].drop_duplicates(subset=keys, keep="first")
    return frame.merge(selected, on=keys, how="left", sort=False)


def _prepare_frame(
    operating: pd.DataFrame,
    weather: pd.DataFrame | None,
    devices: pd.DataFrame | None,
) -> pd.DataFrame:
    frame = operating.copy()
    frame["__row_order__"] = np.arange(len(frame))
    device_key = next(
        (key for key in ("inverter_id", "device_id") if key in frame.columns), None
    )
    scenario_key = "scenario_id" if "scenario_id" in frame.columns else None
    device_keys = [key for key in (scenario_key, device_key) if key]
    frame = _merge_missing_columns(
        frame,
        devices,
        device_keys,
        (
            "rated_ac_power_kw",
            "rated_dc_power_kw",
            "inverter_efficiency",
            "system_losses_fraction",
            "module_temperature_coefficient_per_c",
        ),
    )
    timestamp_key = next((key for key in TIMESTAMP_CANDIDATES if key in frame.columns), None)
    weather_keys = [key for key in (scenario_key, timestamp_key) if key]
    frame = _merge_missing_columns(
        frame,
        weather,
        weather_keys,
        (
            "poa_irradiance_w_m2",
            "ghi_w_m2",
            "solar_elevation_deg",
            "ambient_temperature_c",
        ),
    )
    return (
        frame.sort_values("__row_order__", kind="stable")
        .drop(columns=["__row_order__"])
        .reset_index(drop=True)
    )


def _expected_series(value: Any, frame: pd.DataFrame) -> pd.Series:
    if value is None:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    if isinstance(value, pd.Series):
        return pd.to_numeric(value.reset_index(drop=True), errors="coerce").reindex(frame.index)
    if np.isscalar(value):
        return pd.Series(float(value), index=frame.index, dtype=float)
    return pd.to_numeric(pd.Series(value), errors="coerce").reindex(frame.index)


def _peer_scores(
    frame: pd.DataFrame,
    timestamp_key: str | None,
    device_key: str | None,
    normalized: pd.Series,
    capacity: pd.Series,
    assessable: pd.Series,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    index = frame.index
    median = pd.Series(np.nan, index=index, dtype=float)
    mad = pd.Series(np.nan, index=index, dtype=float)
    zscore = pd.Series(np.nan, index=index, dtype=float)
    status = pd.Series("unavailable", index=index, dtype=object)
    raw = pd.Series(False, index=index, dtype=bool)

    if timestamp_key is None or device_key is None:
        return median, mad, zscore, status, raw

    threshold = float(get_path(config, "anomaly.peer_mad_threshold", 6.0))
    floor = float(get_path(config, "anomaly.peer_mad_floor", 0.01))
    minimum = int(get_path(config, "anomaly.peer_min_devices", 3))
    tolerance = float(get_path(config, "anomaly.capacity_tolerance_ratio", 0.20))
    timestamps = pd.to_datetime(frame[timestamp_key], errors="coerce", utc=True)
    grouping = timestamps.fillna(frame[timestamp_key].astype(str))

    eligible = assessable & normalized.notna() & capacity.notna() & (capacity > 0)
    for _, positions in grouping.groupby(grouping, sort=False).groups.items():
        positions = list(positions)
        candidates = [position for position in positions if bool(eligible.loc[position])]
        if len(candidates) < minimum:
            for position in positions:
                if bool(assessable.loc[position]):
                    status.loc[position] = "insufficient_peers"
            continue
        for target in candidates:
            target_capacity = float(capacity.loc[target])
            peers = [
                position
                for position in candidates
                if position != target
                and abs(float(capacity.loc[position]) - target_capacity)
                / max(target_capacity, 1.0e-9)
                <= tolerance
            ]
            if len(peers) < minimum - 1:
                status.loc[target] = "incomparable_capacity"
                continue
            peer_values = normalized.loc[peers].to_numpy(dtype=float)
            peer_median = float(np.median(peer_values))
            peer_mad = float(np.median(np.abs(peer_values - peer_median)))
            robust_z = 0.6745 * (float(normalized.loc[target]) - peer_median) / max(
                peer_mad, floor
            )
            median.loc[target] = peer_median
            mad.loc[target] = peer_mad
            zscore.loc[target] = robust_z
            status.loc[target] = "ok"
            raw.loc[target] = abs(robust_z) >= threshold
    return median, mad, zscore, status, raw


def _persistence_scores(
    frame: pd.DataFrame,
    timestamp_key: str | None,
    device_key: str | None,
    assessable: pd.Series,
    status: pd.Series,
    peer_raw: pd.Series,
    shortfall: pd.Series,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    index = frame.index
    peer_run = pd.Series(0, index=index, dtype=int)
    peer_alert = pd.Series(False, index=index, dtype=bool)
    shortfall_run = pd.Series(0, index=index, dtype=int)
    residual_alert = pd.Series(False, index=index, dtype=bool)
    cusum_score = pd.Series(0.0, index=index, dtype=float)
    cusum_alert = pd.Series(False, index=index, dtype=bool)

    persistence = max(1, int(get_path(config, "anomaly.persistence_n", 2)))
    shortfall_threshold = float(
        get_path(config, "anomaly.residual_shortfall_threshold", 0.20)
    )
    slack = float(get_path(config, "anomaly.cusum_slack", 0.05))
    cusum_threshold = float(get_path(config, "anomaly.cusum_threshold", 0.50))
    # A gap longer than this many median intervals resets the CUSUM so a score is
    # never carried across missing data.
    gap_factor = float(get_path(config, "anomaly.cusum_gap_reset_intervals", 3.0))
    cusum_cap = cusum_threshold * float(get_path(config, "anomaly.cusum_cap_multiple", 4.0))

    if timestamp_key is None:
        timestamps = pd.Series(np.arange(len(frame)), index=index)
    else:
        timestamps = pd.to_datetime(frame[timestamp_key], errors="coerce", utc=True)
        timestamps = timestamps.fillna(pd.Series(np.arange(len(frame)), index=index))
    devices = (
        frame[device_key].astype(str)
        if device_key is not None and device_key in frame.columns
        else pd.Series("__series__", index=index)
    )
    order = pd.DataFrame({"device": devices, "timestamp": timestamps}, index=index)
    ordered = order.sort_values(["device", "timestamp"], kind="stable")

    for _, rows in ordered.groupby("device", sort=False):
        running_peer = 0
        running_shortfall = 0
        running_cusum = 0.0
        was_alerting = False
        device_times = pd.to_datetime(rows["timestamp"], errors="coerce", utc=True) if timestamp_key else None
        median_step = (
            device_times.diff().dt.total_seconds().median() if device_times is not None and device_times.notna().sum() > 2 else None
        )
        last_assessed = None
        for position in rows.index:
            if bool(assessable.loc[position]):
                if bool(peer_raw.loc[position]):
                    running_peer += 1
                else:
                    running_peer = 0
                value = float(shortfall.loc[position])
                if value >= shortfall_threshold:
                    running_shortfall += 1
                else:
                    running_shortfall = 0
                current = device_times.loc[position] if device_times is not None else None
                if (
                    median_step and last_assessed is not None and current is not None and not pd.isna(current)
                    and (current - last_assessed).total_seconds() > gap_factor * median_step
                    and (current - last_assessed).total_seconds() < 6 * 3600
                ):
                    # Missing intervals (not just night) break the evidence chain.
                    running_cusum = 0.0
                # Standard one-sided CUSUM on the signed shortfall: normal or
                # over-performing intervals reduce the score. The score is capped so
                # one long fault cannot keep a device alerted for days afterwards.
                running_cusum = min(max(0.0, running_cusum + value - slack), cusum_cap)
                if was_alerting and value <= slack:
                    running_cusum = 0.0  # the alert run completed on a normal interval
                # Alert only while the current interval itself is short.
                alerting = running_cusum >= cusum_threshold and value > slack
                was_alerting = alerting
                last_assessed = current
            else:
                running_peer = 0
                running_shortfall = 0
                if str(status.loc[position]) == "unavailable":
                    running_cusum = 0.0
            peer_run.loc[position] = running_peer
            shortfall_run.loc[position] = running_shortfall
            cusum_score.loc[position] = running_cusum
            peer_alert.loc[position] = running_peer >= persistence
            residual_alert.loc[position] = running_shortfall >= persistence
            cusum_alert.loc[position] = (
                bool(assessable.loc[position]) and running_cusum >= cusum_threshold
                and float(shortfall.loc[position]) > slack
            )
    return peer_run, peer_alert, shortfall_run, residual_alert, cusum_score, cusum_alert


def detect_anomalies(
    operating: pd.DataFrame,
    *,
    weather: pd.DataFrame | None = None,
    devices: pd.DataFrame | None = None,
    mapping: Any | None = None,
    config: dict[str, Any] | None = None,
    expected_power_kw: Any | None = None,
    actual_column: str | None = None,
    expected_column: str | None = None,
    device_column: str | None = None,
    timestamp_column: str | None = None,
    poa_column: str | None = None,
    ghi_column: str | None = None,
    solar_elevation_column: str | None = None,
    capacity_column: str | None = None,
) -> dict[str, Any]:
    """Detect peer-relative and residual anomalies without assigning causes."""

    config = config or load_defaults()
    mapping_columns = _mapping_lookup(mapping)
    frame = _prepare_frame(operating, weather, devices)
    index = frame.index

    actual_name = _find(frame, actual_column, ACTUAL_CANDIDATES, "power_ac", mapping_columns)
    expected_name = _find(
        frame, expected_column, EXPECTED_CANDIDATES, "expected_power", mapping_columns
    )
    device_name = _find(frame, device_column, DEVICE_CANDIDATES, "device_id", mapping_columns)
    timestamp_name = _find(
        frame, timestamp_column, TIMESTAMP_CANDIDATES, "timestamp", mapping_columns
    )
    poa_name = _find(frame, poa_column, POA_CANDIDATES, "irradiance_poa", mapping_columns)
    ghi_name = _find(frame, ghi_column, GHI_CANDIDATES, "irradiance_ghi", mapping_columns)
    sun_name = _find(frame, solar_elevation_column, SUN_CANDIDATES, "sun_elevation", mapping_columns)
    capacity_name = _find(
        frame, capacity_column, CAPACITY_CANDIDATES, "capacity", mapping_columns
    )
    dc_capacity_name = _find(
        frame, None, DC_CAPACITY_CANDIDATES, "dc_capacity", mapping_columns
    )
    efficiency_name = _find(
        frame, None, EFFICIENCY_CANDIDATES, "inverter_efficiency", mapping_columns
    )
    losses_name = _find(frame, None, LOSSES_CANDIDATES, "system_losses", mapping_columns)
    gamma_name = _find(
        frame, None, GAMMA_CANDIDATES, "temperature_coefficient", mapping_columns
    )
    module_name = _find(
        frame, None, MODULE_TEMP_CANDIDATES, "module_temperature", mapping_columns
    )
    ambient_name = _find(
        frame, None, AMBIENT_TEMP_CANDIDATES, "ambient_temperature", mapping_columns
    )

    baseline_result: dict[str, Any] | None = None
    if expected_power_kw is not None:
        expected = _expected_series(expected_power_kw, frame)
    elif expected_name is not None:
        expected = _numeric(frame, expected_name)
    else:
        baseline_result = physics_baseline(
            frame,
            config=config,
            poa_column=poa_name,
            ghi_column=ghi_name,
            module_temperature_column=module_name,
            ambient_temperature_column=ambient_name,
            capacity_column=capacity_name,
            dc_capacity_column=dc_capacity_name,
            inverter_efficiency_column=efficiency_name,
            system_losses_column=losses_name,
            temperature_coefficient_column=gamma_name,
            timestamp_column=timestamp_name,
            device_column=device_name,
        )
        expected = baseline_result["expected_power_kw"].reset_index(drop=True)

    actual = _numeric(frame, actual_name)
    capacity = _numeric(frame, capacity_name)
    poa = _numeric(frame, poa_name)
    sun = _numeric(frame, sun_name)
    timestamps = (
        frame[timestamp_name]
        if timestamp_name is not None
        else pd.Series(np.nan, index=index)
    )

    night_threshold = float(
        get_path(
            config,
            "anomaly.night_sun_elevation_deg",
            get_path(config, "validation.night.sun_elevation_threshold_deg", -0.833),
        )
    )
    min_irradiance = float(get_path(config, "anomaly.min_irradiance_w_m2", 50.0))
    fraction = float(get_path(config, "anomaly.min_expected_power_fraction", 0.01))
    floor_power = float(get_path(config, "anomaly.min_expected_power_kw", 0.5))

    night = sun.notna() & (sun <= night_threshold)
    low_irradiance = poa.notna() & (poa < min_irradiance)
    comparable_min = np.maximum(floor_power, fraction * capacity.fillna(0.0))
    low_expected = expected.notna() & (expected < comparable_min)
    invalid_actual = actual.notna() & (actual < 0.0)

    status = pd.Series("assessed", index=index, dtype=object)
    reason = pd.Series("", index=index, dtype=object)
    missing_actual = actual.isna()
    missing_expected = expected.isna()
    missing_irradiance = poa.isna()
    status.loc[missing_actual] = "unavailable"
    reason.loc[missing_actual] = "actual power is missing; treated as unavailable, not zero"
    status.loc[~missing_actual & missing_expected] = "unavailable"
    reason.loc[~missing_actual & missing_expected] = (
        "expected power is missing; no residual assessment is possible"
    )
    status.loc[~missing_actual & ~missing_expected & missing_irradiance] = "unavailable"
    reason.loc[~missing_actual & ~missing_expected & missing_irradiance] = (
        "irradiance is missing; no assessment is possible"
    )
    status.loc[status.eq("assessed") & invalid_actual] = "unavailable"
    reason.loc[status.eq("unavailable") & invalid_actual] = (
        "negative actual power is invalid; treated as unavailable"
    )
    status.loc[status.eq("assessed") & night] = "suppressed_night"
    reason.loc[status.eq("suppressed_night")] = "nighttime interval; alert suppressed"
    status.loc[status.eq("assessed") & ~night & low_irradiance] = "suppressed_low_irradiance"
    reason.loc[status.eq("suppressed_low_irradiance")] = (
        "irradiance is below the assessment threshold; alert suppressed"
    )
    status.loc[
        status.eq("assessed") & ~night & ~low_irradiance & low_expected
    ] = "suppressed_low_expected_output"
    reason.loc[status.eq("suppressed_low_expected_output")] = (
        "physics-expected output is below the assessment floor"
    )

    assessable = status.eq("assessed")
    normalized = pd.Series(np.nan, index=index, dtype=float)
    normalized.loc[assessable] = (
        actual.loc[assessable] / expected.loc[assessable]
    )
    shortfall = pd.Series(np.nan, index=index, dtype=float)
    shortfall.loc[assessable] = 1.0 - normalized.loc[assessable]

    peer_median, peer_mad, peer_z, peer_status, peer_raw = _peer_scores(
        frame, timestamp_name, device_name, normalized, capacity, assessable, config
    )
    (
        peer_persistence,
        peer_alert,
        residual_persistence,
        residual_alert,
        cusum_score,
        cusum_alert,
    ) = _persistence_scores(
        frame,
        timestamp_name,
        device_name,
        assessable,
        status,
        peer_raw,
        shortfall,
        config,
    )

    checks: list[list[str]] = []
    messages: list[str] = []
    for position in index:
        row_checks: list[str] = []
        row_messages: list[str] = []
        if bool(peer_alert.loc[position]):
            row_checks.append("peer_output_deviation")
            direction = "below" if float(peer_z.loc[position]) < 0.0 else "above"
            row_messages.append(
                f"Output is {direction} the median of comparable peers for "
                f"{int(peer_persistence.loc[position])} consecutive intervals."
            )
        if bool(residual_alert.loc[position]):
            row_checks.append("residual_shortfall")
            row_messages.append("Sustained shortfall versus physics-expected output.")
        elif bool(cusum_alert.loc[position]):
            row_checks.append("cumulative_shortfall")
            row_messages.append("Accumulated shortfall versus physics-expected output (CUSUM).")
        checks.append(row_checks)
        messages.append(" ".join(row_messages))

    assessments = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "inverter_id": frame[device_name] if device_name else "__series__",
            "actual_power_kw": actual,
            "expected_power_kw": expected,
            "normalized_output": normalized,
            "residual_shortfall": shortfall,
            "poa_irradiance_w_m2": poa,
            "solar_elevation_deg": sun,
            "capacity_kw": capacity,
            "status": status,
            "reason": reason,
            "peer_status": peer_status,
            "peer_median": peer_median,
            "peer_mad": peer_mad,
            "peer_z": peer_z,
            "peer_persistence": peer_persistence,
            "peer_alert": peer_alert,
            "residual_persistence": residual_persistence,
            "residual_alert": residual_alert,
            "cusum_score": cusum_score,
            "cusum_alert": cusum_alert,
            "alert": [bool(item) for item in checks],
            "alert_checks": checks,
            "message": messages,
        },
        index=index,
    )

    alerts: list[dict[str, Any]] = []
    for position in index:
        if not bool(assessments.at[position, "alert"]):
            continue
        alerts.append(
            json_safe(
                {
                    "timestamp_utc": assessments.at[position, "timestamp_utc"],
                    "inverter_id": assessments.at[position, "inverter_id"],
                    "status": "suspected",
                    "checks": assessments.at[position, "alert_checks"],
                    "message": assessments.at[position, "message"],
                    "evidence": {
                        "actual_power_kw": assessments.at[position, "actual_power_kw"],
                        "expected_power_kw": assessments.at[position, "expected_power_kw"],
                        "normalized_output": assessments.at[position, "normalized_output"],
                        "poa_irradiance_w_m2": assessments.at[position, "poa_irradiance_w_m2"],
                        "peer_median": assessments.at[position, "peer_median"],
                        "peer_mad": assessments.at[position, "peer_mad"],
                        "peer_z": assessments.at[position, "peer_z"],
                        "peer_persistence": assessments.at[position, "peer_persistence"],
                        "residual_shortfall": assessments.at[position, "residual_shortfall"],
                        "cusum_score": assessments.at[position, "cusum_score"],
                    },
                    "missing_evidence": [
                        "event log, device status and inspection are needed to determine cause"
                    ],
                }
            )
        )

    peer_scores = peer_z.abs().dropna()
    cusum_values = cusum_score.dropna()
    anomaly_score = float(peer_scores.max()) if len(peer_scores) else 0.0
    return {
        "rows": int(len(frame)),
        "status": "warning" if alerts else "ok",
        "anomaly_score": anomaly_score,
        "max_cusum": float(cusum_values.max()) if len(cusum_values) else 0.0,
        "alerts": alerts,
        "assessments": assessments,
        "counts": {
            "assessed": int(assessable.sum()),
            "unavailable": int(status.eq("unavailable").sum()),
            "suppressed_night": int(status.eq("suppressed_night").sum()),
            "suppressed_low_irradiance": int(status.eq("suppressed_low_irradiance").sum()),
            "suppressed_low_expected_output": int(
                status.eq("suppressed_low_expected_output").sum()
            ),
        },
        "baseline": (
            {
                "status": baseline_result["status"],
                "warnings": baseline_result["warnings"],
            }
            if baseline_result is not None
            else None
        ),
        "columns": {
            "actual": actual_name,
            "expected": expected_name,
            "device": device_name,
            "timestamp": timestamp_name,
            "poa": poa_name,
            "capacity": capacity_name,
        },
        "limitations": [
            "Peer checks require sufficient same-time devices with comparable rated capacity.",
            "Residual checks inherit the documented physics-baseline assumptions.",
            "Alerts indicate unusual behavior and are not root-cause findings.",
        ],
    }


def peer_mad(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    """Return peer/MAD scores and anomalies for a compatible frame."""

    result = detect_anomalies(frame, **kwargs)
    return {
        "rows": result["rows"],
        "status": result["status"],
        "anomaly_score": result["anomaly_score"],
        "alerts": result["alerts"],
        "assessments": result["assessments"],
    }


def cusum(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    """Return residual-CUSUM scores and residual-triggered anomalies."""

    result = detect_anomalies(frame, **kwargs)
    residual_alerts = [
        alert
        for alert in result["alerts"]
        if "residual_shortfall" in alert.get("checks", [])
    ]
    return {
        "rows": result["rows"],
        "status": result["status"],
        "cusum": result["max_cusum"],
        "alerts": residual_alerts,
        "assessments": result["assessments"],
    }
