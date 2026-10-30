"""Deterministic data-quality validation.

Checks never repair data.  They report counts, affected devices, example time
ranges and limitations so that missing or implausible readings remain visible.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .config import get_path, json_safe, load_defaults
from .ingestion import LOCAL_COLUMN, RAW_TIMESTAMP_COLUMN, ROW_ORDER_COLUMN, UTC_COLUMN
from .schema_mapping import (
    NUMERIC_ROLES,
    apply_conversion,
    numeric_values,
)


def _check(
    check_id: str,
    status: str,
    message: str,
    *,
    count: int = 0,
    affected_devices: Iterable[str] | None = None,
    time_ranges: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "count": int(count),
        "message": message,
        "affected_devices": json_safe(sorted({str(item) for item in (affected_devices or []) if item is not None})),
        "time_ranges": json_safe(time_ranges or []),
        "details": json_safe(details or {}),
    }


def _mapping_fields(mapping: Any) -> list[dict[str, Any]]:
    if mapping is None:
        return []
    if isinstance(mapping, dict):
        return list(mapping.get("fields", []))
    return list(getattr(mapping, "fields", []))


def _mapping_role_columns(mapping: Any) -> dict[str, list[str]]:
    if mapping is None:
        return {}
    if isinstance(mapping, dict):
        return {str(role): [str(column) for column in columns] for role, columns in mapping.get("role_to_columns", {}).items()}
    return {str(role): [str(column) for column in columns] for role, columns in getattr(mapping, "role_to_columns", {}).items()}


def _field_for_column(fields: list[dict[str, Any]], column: str) -> dict[str, Any] | None:
    for item in fields:
        if str(item.get("internal_column")) == str(column):
            return item
    return None


def _series_for(frame: pd.DataFrame, column: str) -> pd.Series | None:
    if column in frame.columns:
        return frame[column]
    for candidate in frame.columns:
        if str(candidate) == str(column):
            return frame[candidate]
    return None


def _timestamp_values(frame: pd.DataFrame) -> tuple[pd.Series | None, str]:
    if UTC_COLUMN in frame.columns and frame[UTC_COLUMN].notna().any():
        return frame[UTC_COLUMN], "utc"
    if LOCAL_COLUMN in frame.columns and frame[LOCAL_COLUMN].notna().any():
        return frame[LOCAL_COLUMN], "local"
    if RAW_TIMESTAMP_COLUMN in frame.columns and frame[RAW_TIMESTAMP_COLUMN].notna().any():
        return frame[RAW_TIMESTAMP_COLUMN], "raw"
    return None, "none"


def _iter_device_groups(
    frame: pd.DataFrame,
    layout: dict[str, Any],
) -> list[tuple[str | None, pd.Index]]:
    """Return (device, row-index) groups.

    In long layout, a timestamp legitimately repeats once per device.  All
    temporal checks must therefore run within a device group.
    """

    device_column = layout.get("device_column")
    if device_column and device_column in frame.columns:
        groups: list[tuple[str | None, pd.Index]] = []
        for device, indexes in frame.groupby(device_column, dropna=False, sort=False).groups.items():
            groups.append((str(device), indexes))
        return groups
    return [(None, frame.index)]


def _row_indices(mask: pd.Series) -> list[int]:
    if mask is None or len(mask) == 0:
        return []
    return [int(value) for value in np.flatnonzero(mask.fillna(False).to_numpy())]


def _time_ranges(
    mask: pd.Series,
    frame: pd.DataFrame,
    max_ranges: int,
) -> list[dict[str, Any]]:
    indices = _row_indices(mask)
    if not indices:
        return []
    values, source = _timestamp_values(frame)
    ranges: list[dict[str, Any]] = []
    start = indices[0]
    previous = indices[0]
    for index in indices[1:]:
        if index != previous + 1:
            ranges.append((start, previous))
            start = index
        previous = index
    ranges.append((start, previous))

    results: list[dict[str, Any]] = []
    for first, last in ranges[:max_ranges]:
        if values is not None and source in {"utc", "local"}:
            start_value = values.iloc[first]
            end_value = values.iloc[last]
        elif values is not None:
            start_value = values.iloc[first]
            end_value = values.iloc[last]
        else:
            start_value = int(frame[ROW_ORDER_COLUMN].iloc[first]) if ROW_ORDER_COLUMN in frame.columns else first
            end_value = int(frame[ROW_ORDER_COLUMN].iloc[last]) if ROW_ORDER_COLUMN in frame.columns else last
        results.append(
            {
                "start": json_safe(start_value),
                "end": json_safe(end_value),
                "row_start": int(first),
                "row_end": int(last),
                "timestamp_basis": source,
            }
        )
    return results


def _device_values(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    mask: pd.Series,
    field: dict[str, Any] | None = None,
) -> list[str]:
    indices = _row_indices(mask)
    if not indices:
        return []
    device_column = layout.get("device_column")
    if device_column and device_column in frame.columns:
        return [str(value) for value in frame[device_column].iloc[indices].dropna().unique()]
    if field is not None and field.get("device_id") is not None:
        return [str(field["device_id"])]
    return [str(item) for item in layout.get("devices", [])]


def _check_duplicates(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    values, source = _timestamp_values(frame)
    if values is None:
        return _check("duplicate_timestamps", "not_checked", "No usable timestamp values are available.")
    mask = pd.Series(False, index=frame.index)
    duplicated_rows = 0
    by_device: dict[str, int] = {}
    affected: set[str] = set()
    for device, indexes in _iter_device_groups(frame, layout):
        group = values.loc[indexes]
        extra = int(group.duplicated(keep="first").sum())
        if not extra:
            continue
        duplicated_rows += extra
        by_device[device or "<series>"] = extra
        if device is not None:
            affected.add(device)
        mask.loc[indexes] = group.duplicated(keep=False).to_numpy()
    if source == "raw":
        message = "Exact duplicate raw timestamp strings were counted within each device group; time-zone normalization was unavailable."
    else:
        message = "Duplicate timestamp values were counted within each device group."
    return _check(
        "duplicate_timestamps",
        "fail" if duplicated_rows else "pass",
        message,
        count=duplicated_rows,
        affected_devices=sorted(affected) if affected else _device_values(frame, layout, mask),
        time_ranges=_time_ranges(mask, frame, int(get_path(config, "validation.max_example_ranges", 20))),
        details={
            "timestamp_basis": source,
            "duplicate_rows_including_first": int(mask.sum()),
            "by_device": by_device,
        },
    )


def _check_order(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    config: dict[str, Any],
    timezone_resolved: bool,
) -> dict[str, Any]:
    values = None
    source = "none"
    if UTC_COLUMN in frame.columns and frame[UTC_COLUMN].notna().any():
        values = frame[UTC_COLUMN]
        source = "utc"
    elif LOCAL_COLUMN in frame.columns and frame[LOCAL_COLUMN].notna().any():
        values = frame[LOCAL_COLUMN]
        source = "local"
    if values is None:
        return _check("out_of_order_timestamps", "not_checked", "No parsed timestamps are available.")
    if source == "local" and not timezone_resolved:
        basis_note = "Rows were checked using parsed local time within each device group; UTC conversion is unresolved."
    else:
        basis_note = "Rows were checked using normalized UTC time within each device group."
    mask = pd.Series(False, index=frame.index)
    count = 0
    by_device: dict[str, int] = {}
    affected: set[str] = set()
    for device, indexes in _iter_device_groups(frame, layout):
        group = pd.Series(pd.to_datetime(values.loc[indexes], errors="coerce"), index=indexes)
        local_mask = group.diff().dt.total_seconds() < 0
        local_count = int(local_mask.sum())
        if not local_count:
            continue
        count += local_count
        by_device[device or "<series>"] = local_count
        if device is not None:
            affected.add(device)
        mask.loc[indexes] = local_mask.to_numpy()
    return _check(
        "out_of_order_timestamps",
        "fail" if count else "pass",
        basis_note,
        count=count,
        affected_devices=sorted(affected) if affected else _device_values(frame, layout, mask),
        time_ranges=_time_ranges(mask, frame, int(get_path(config, "validation.max_example_ranges", 20))),
        details={"timestamp_basis": source, "by_device": by_device},
    )


def _check_gaps(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    timestamp_info: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    if timestamp_info.get("status") != "resolved" or UTC_COLUMN not in frame.columns:
        return _check(
            "time_gaps",
            "not_checked",
            "Time gaps could not be checked because the timestamp or time zone is unresolved.",
            details={"ambiguity": timestamp_info.get("ambiguity", [])},
        )
    factor = float(get_path(config, "validation.gap_tolerance_factor", 1.5))
    minimum = float(get_path(config, "validation.minimum_gap_seconds", 1.0))
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))
    expected = timestamp_info.get("sampling_interval_seconds")
    ranges: list[dict[str, Any]] = []
    gap_count = 0
    max_gap = 0.0
    by_device: dict[str, int] = {}
    affected: set[str] = set()
    checked_groups = 0
    thresholds: list[float] = []
    expected_values: list[float] = []
    for device, indexes in _iter_device_groups(frame, layout):
        timestamps = frame.loc[indexes, UTC_COLUMN].dropna().sort_values().reset_index(drop=True)
        if len(timestamps) < 3:
            continue
        checked_groups += 1
        diffs = timestamps.diff().dt.total_seconds().dropna()
        positive = diffs[diffs > 0]
        group_expected = expected
        if group_expected is None or group_expected <= 0:
            group_expected = float(positive.median()) if not positive.empty else None
        elif not positive.empty:
            # A single large gap can inflate the median.  Use the smallest
            # observed positive cadence so a missing interval remains visible.
            group_expected = min(float(group_expected), float(positive.min()))
        if group_expected is None or group_expected <= 0:
            continue
        threshold = max(group_expected * factor, minimum)
        thresholds.append(threshold)
        expected_values.append(float(group_expected))
        gap_mask = diffs > threshold
        local_count = int(gap_mask.sum())
        if not local_count:
            continue
        gap_count += local_count
        by_device[device or "<series>"] = local_count
        if device is not None:
            affected.add(device)
        max_gap = max(max_gap, float(diffs.max()) if len(diffs) else 0.0)
        for position in np.flatnonzero(gap_mask.to_numpy()):
            if len(ranges) >= max_ranges:
                break
            ranges.append(
                {
                    "start": json_safe(timestamps.iloc[int(position)]),
                    "end": json_safe(timestamps.iloc[int(position) + 1]),
                    "gap_seconds": float(diffs.iloc[int(position)]),
                    "timestamp_basis": "utc",
                    "device": device,
                }
            )
    if checked_groups == 0:
        return _check("time_gaps", "not_checked", "Fewer than three valid timestamps are available per device group.")
    if not thresholds:
        return _check("time_gaps", "not_checked", "A sampling interval could not be established per device group.")
    status = "warning" if gap_count else "pass"
    threshold_text = min(thresholds) if len(set(thresholds)) == 1 else "per-device"
    threshold_value = float(thresholds[0]) if len(set(thresholds)) == 1 else None
    return _check(
        "time_gaps",
        status,
        f"Found {gap_count} gap(s) larger than the configured per-device threshold.",
        count=gap_count,
        affected_devices=sorted(affected) if affected else [],
        time_ranges=ranges,
        details={
            "expected_interval_seconds": min(expected_values) if expected_values else None,
            "threshold_seconds": threshold_value,
            "threshold_text": threshold_text,
            "maximum_gap_seconds": max_gap,
            "by_device": by_device,
        },
    )


def _check_missing(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    fields: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    accepted = [item for item in fields if item.get("canonical_role") and not item.get("unresolved")]
    if not accepted:
        return _check("missing_values", "not_checked", "No accepted mapped fields are available.")
    minimum_fraction = float(get_path(config, "validation.missing_min_valid_fraction", 0.8))
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))
    details: dict[str, Any] = {}
    affected: list[str] = []
    failing_columns: list[str] = []
    ranges: list[dict[str, Any]] = []
    total_missing = 0
    for field in accepted:
        column = str(field.get("internal_column"))
        series = _series_for(frame, column)
        if series is None:
            continue
        missing = int(series.isna().sum())
        total_missing += missing
        fraction = float(series.notna().mean())
        details[column] = {
            "role": field.get("canonical_role"),
            "missing": missing,
            "valid_fraction": round(fraction, 4),
        }
        if missing:
            mask = series.isna()
            affected.extend(_device_values(frame, layout, mask, field))
            if len(ranges) < max_ranges:
                ranges.extend(_time_ranges(mask, frame, max_ranges - len(ranges)))
            if fraction < minimum_fraction:
                failing_columns.append(column)
    if failing_columns:
        status = "fail"
        message = "One or more mapped measurement columns fall below the minimum valid fraction."
    elif total_missing:
        status = "warning"
        message = "Missing readings were retained as NaN."
    else:
        status = "pass"
        message = "No missing readings in accepted mapped fields."
    return _check(
        "missing_values",
        status,
        message,
        count=total_missing,
        affected_devices=affected,
        time_ranges=ranges,
        details={"columns": details, "minimum_valid_fraction": minimum_fraction, "failing_columns": failing_columns},
    )


def _capacity_series(
    frame: pd.DataFrame,
    fields: list[dict[str, Any]],
) -> tuple[pd.Series | None, float | None]:
    capacity_fields = [item for item in fields if item.get("canonical_role") == "capacity" and not item.get("unresolved")]
    if not capacity_fields:
        return None, None
    field = capacity_fields[0]
    series = _series_for(frame, str(field.get("internal_column")))
    if series is None:
        return None, None
    converted = apply_conversion(series, field.get("conversion"))
    unique = converted.dropna().unique()
    constant = float(unique[0]) if len(unique) == 1 else None
    return converted, constant


def _check_impossible(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    fields: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    plaus = config.get("plausibility", {})
    capacity_series, capacity_constant = _capacity_series(frame, fields)
    checks: list[dict[str, Any]] = []
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))

    def record(
        check_id: str,
        mask: pd.Series,
        field: dict[str, Any],
        message: str,
        details: dict[str, Any] | None = None,
        severity: str = "fail",
    ) -> None:
        count = int(mask.fillna(False).sum())
        if not count:
            return
        checks.append(
            _check(
                check_id,
                severity,
                message,
                count=count,
                affected_devices=_device_values(frame, layout, mask, field),
                time_ranges=_time_ranges(mask, frame, max_ranges),
                details={"column": field.get("source_column"), **dict(details or {})},
            )
        )

    for field in fields:
        role = field.get("canonical_role")
        if role not in NUMERIC_ROLES or field.get("unresolved"):
            continue
        column = str(field.get("internal_column"))
        series = _series_for(frame, column)
        if series is None:
            continue
        values = apply_conversion(series, field.get("conversion"))
        if role in {"power_ac", "power_dc"}:
            if not bool(plaus.get("allow_negative_power", False)):
                record(
                    "negative_power",
                    values < float(plaus.get("power_min_kw", 0.0)) - float(plaus.get("power_negative_tolerance_kw", 0.0)),
                    field,
                    "Negative power readings were found.",
                    {"minimum_kw": float(plaus.get("power_min_kw", 0.0))},
                )
            if capacity_series is not None:
                limit = capacity_series * float(plaus.get("capacity_tolerance_ratio", 1.2))
                mask = pd.Series(values.to_numpy() > limit.to_numpy(), index=frame.index)
                record(
                    "power_above_capacity",
                    mask,
                    field,
                    "Power readings exceed documented capacity times the configured tolerance.",
                    {
                        "capacity_source": "mapped capacity column",
                        "capacity_tolerance_ratio": float(plaus.get("capacity_tolerance_ratio", 1.2)),
                    },
                )
            elif capacity_constant is not None:
                limit = capacity_constant * float(plaus.get("capacity_tolerance_ratio", 1.2))
                record(
                    "power_above_capacity",
                    values > limit,
                    field,
                    "Power readings exceed documented capacity times the configured tolerance.",
                    {"capacity_kw": capacity_constant, "capacity_tolerance_ratio": float(plaus.get("capacity_tolerance_ratio", 1.2))},
                )
        elif role in {"irradiance_poa", "irradiance_ghi"}:
            record(
                "irradiance_below_minimum",
                values < float(plaus.get("irradiance_min_w_m2", 0.0)),
                field,
                "Irradiance readings are below the configured minimum.",
                {"minimum_w_m2": float(plaus.get("irradiance_min_w_m2", 0.0))},
                severity="warning",
            )
            record(
                "irradiance_above_maximum",
                values > float(plaus.get("irradiance_max_w_m2", 1500.0)),
                field,
                "Irradiance readings exceed the configured plausible maximum.",
                {"maximum_w_m2": float(plaus.get("irradiance_max_w_m2", 1500.0))},
            )
        elif role == "ambient_temperature":
            mask = (values < float(plaus.get("ambient_temperature_min_c", -50.0))) | (
                values > float(plaus.get("ambient_temperature_max_c", 70.0))
            )
            record("ambient_temperature_out_of_range", mask, field, "Ambient temperature is outside the configured range.")
        elif role == "module_temperature":
            mask = (values < float(plaus.get("module_temperature_min_c", -50.0))) | (
                values > float(plaus.get("module_temperature_max_c", 100.0))
            )
            record("module_temperature_out_of_range", mask, field, "Module temperature is outside the configured range.")
        elif role in {"energy_interval", "energy_cumulative"}:
            record(
                "negative_energy",
                values < float(plaus.get("energy_min_kwh", 0.0)),
                field,
                "Negative energy readings were found.",
                {"minimum_kwh": float(plaus.get("energy_min_kwh", 0.0))},
                severity="warning",
            )
        elif role == "capacity":
            record(
                "capacity_nonpositive",
                values <= float(plaus.get("capacity_min_kw", 0.0)),
                field,
                "Capacity readings are not positive.",
            )
    return checks


def _grouped_series(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    field: dict[str, Any],
    values: pd.Series,
) -> list[tuple[str | None, pd.Series]]:
    device_column = layout.get("device_column")
    if device_column and device_column in frame.columns:
        groups: list[tuple[str | None, pd.Series]] = []
        for device, indexes in frame.groupby(device_column, dropna=False).groups.items():
            group_values = values.loc[indexes]
            groups.append((str(device), group_values))
        return groups
    return [(field.get("device_id"), values)]


def _sort_by_time(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    if UTC_COLUMN in frame.columns and frame[UTC_COLUMN].notna().any():
        order = frame[UTC_COLUMN].sort_values().index
        return values.loc[order]
    if LOCAL_COLUMN in frame.columns and frame[LOCAL_COLUMN].notna().any():
        order = frame[LOCAL_COLUMN].sort_values().index
        return values.loc[order]
    return values


def _check_cumulative_resets(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    fields: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    tolerance = float(get_path(config, "validation.cumulative_reset_tolerance", 1e-9))
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))
    checks: list[dict[str, Any]] = []
    for field in fields:
        if field.get("canonical_role") != "energy_cumulative" or field.get("unresolved"):
            continue
        column = str(field.get("internal_column"))
        series = _series_for(frame, column)
        if series is None:
            continue
        values = apply_conversion(series, field.get("conversion"))
        for device, group in _grouped_series(frame, layout, field, values):
            ordered = _sort_by_time(frame, group)
            decreases = ordered.diff() < -tolerance
            count = int(decreases.sum())
            if not count:
                continue
            positions = np.flatnonzero(decreases.to_numpy())[:max_ranges]
            ranges = []
            for position in positions:
                current_index = ordered.index[int(position)]
                previous_index = ordered.index[max(int(position) - 1, 0)]
                start_value: Any = previous_index
                end_value: Any = current_index
                basis = "row_index"
                for candidate, candidate_basis in [
                    (UTC_COLUMN, "utc"),
                    (LOCAL_COLUMN, "local"),
                    (RAW_TIMESTAMP_COLUMN, "raw"),
                ]:
                    if candidate in frame.columns:
                        start_candidate = frame.at[previous_index, candidate]
                        end_candidate = frame.at[current_index, candidate]
                        if not pd.isna(start_candidate) and not pd.isna(end_candidate):
                            start_value = start_candidate
                            end_value = end_candidate
                            basis = candidate_basis
                            break
                ranges.append(
                    {
                        "start": json_safe(start_value),
                        "end": json_safe(end_value),
                        "row_start": int(previous_index),
                        "row_end": int(current_index),
                        "timestamp_basis": basis,
                    }
                )
            checks.append(
                _check(
                    "cumulative_counter_reset",
                    "fail",
                    "A cumulative counter decreased; this may be a reset, rollover, meter replacement or data error.",
                    count=count,
                    affected_devices=[device] if device else [],
                    time_ranges=ranges,
                    details={"column": field.get("source_column"), "tolerance": tolerance},
                )
            )
    return checks


def _check_flatlines(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    fields: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    min_points = int(get_path(config, "validation.flatline_min_points", 6))
    tolerance = float(get_path(config, "validation.flatline_value_tolerance", 1e-9))
    ignore_zero = bool(get_path(config, "validation.flatline_ignore_zero", True))
    roles = set(get_path(config, "validation.flatline_roles", []))
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))
    checks: list[dict[str, Any]] = []

    def runs(values: pd.Series) -> list[tuple[int, int]]:
        found: list[tuple[int, int]] = []
        start = None
        previous = None
        for position, value in enumerate(values.tolist()):
            if value is None or (isinstance(value, float) and not math.isfinite(value)) or pd.isna(value):
                if start is not None and previous is not None and previous - start + 1 >= min_points:
                    found.append((start, previous))
                start = None
                previous = None
                continue
            if ignore_zero and abs(float(value)) <= tolerance:
                if start is not None and previous is not None and previous - start + 1 >= min_points:
                    found.append((start, previous))
                start = None
                previous = None
                continue
            if start is None:
                start = position
                previous = position
            elif abs(float(value) - float(values.iloc[previous])) <= tolerance:
                previous = position
            else:
                if previous - start + 1 >= min_points:
                    found.append((start, previous))
                start = position
                previous = position
        if start is not None and previous is not None and previous - start + 1 >= min_points:
            found.append((start, previous))
        return found

    for field in fields:
        if field.get("canonical_role") not in roles or field.get("unresolved"):
            continue
        column = str(field.get("internal_column"))
        series = _series_for(frame, column)
        if series is None:
            continue
        values = apply_conversion(series, field.get("conversion"))
        for device, group in _grouped_series(frame, layout, field, values):
            found = runs(group)
            if not found:
                continue
            longest = max(end - start + 1 for start, end in found)
            mask = pd.Series(False, index=frame.index)
            for start, end in found:
                local_indexes = group.index[start : end + 1]
                mask.loc[local_indexes] = True
            checks.append(
                _check(
                    "suspicious_flatline",
                    "warning",
                    "A sensor or output series is flat for at least the configured minimum run length.",
                    count=len(found),
                    affected_devices=[device] if device else [],
                    time_ranges=_time_ranges(mask, frame, max_ranges),
                    details={
                        "column": field.get("source_column"),
                        "role": field.get("canonical_role"),
                        "run_count": len(found),
                        "longest_run_points": int(longest),
                        "minimum_run_points": min_points,
                        "zero_values_ignored": ignore_zero,
                    },
                )
            )
    return checks


def solar_elevation_deg(times_utc: pd.Series, latitude: float, longitude: float) -> pd.Series:
    """Approximate solar elevation for a night-time screening check.

    This is the standard NOAA fractional-year approximation.  It is used only
    to flag readings that merit review, not as a calibrated solar-position
    product.
    """

    times = pd.to_datetime(times_utc, utc=True, errors="coerce")
    day = times.dt.dayofyear.astype(float)
    hour = times.dt.hour.astype(float) + times.dt.minute.astype(float) / 60.0 + times.dt.second.astype(float) / 3600.0
    gamma = 2.0 * np.pi / 365.0 * (day - 1.0 + (hour - 12.0) / 24.0)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2.0 * gamma)
        - 0.040849 * np.sin(2.0 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2.0 * gamma)
        + 0.000907 * np.sin(2.0 * gamma)
        - 0.002697 * np.cos(3.0 * gamma)
        + 0.00148 * np.sin(3.0 * gamma)
    )
    true_solar_time = hour * 60.0 + eqtime + 4.0 * float(longitude)
    hour_angle = np.deg2rad(true_solar_time / 4.0 - 180.0)
    latitude_rad = np.deg2rad(float(latitude))
    cos_zenith = (
        np.sin(latitude_rad) * np.sin(declination)
        + np.cos(latitude_rad) * np.cos(declination) * np.cos(hour_angle)
    )
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)
    return pd.Series(90.0 - np.rad2deg(np.arccos(cos_zenith)), index=times_utc.index)


def _check_night_generation(
    frame: pd.DataFrame,
    layout: dict[str, Any],
    fields: list[dict[str, Any]],
    config: dict[str, Any],
    timestamp_info: dict[str, Any],
    location: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    location = location or get_path(config, "validation.location", {}) or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return [
            _check(
                "night_time_generation",
                "not_checked",
                "Night-time generation was not checked because latitude/longitude were not supplied.",
            )
        ]
    if timestamp_info.get("status") != "resolved" or UTC_COLUMN not in frame.columns:
        return [
            _check(
                "night_time_generation",
                "not_checked",
                "Night-time generation was not checked because UTC timestamps are unresolved.",
            )
        ]
    elevation = solar_elevation_deg(frame[UTC_COLUMN], float(latitude), float(longitude))
    threshold = float(get_path(config, "validation.night.sun_elevation_threshold_deg", -0.833))
    night = elevation < threshold
    checks: list[dict[str, Any]] = []
    max_ranges = int(get_path(config, "validation.max_example_ranges", 20))
    for field in fields:
        role = field.get("canonical_role")
        if field.get("unresolved") or role not in {"power_ac", "power_dc", "energy_interval", "irradiance_poa", "irradiance_ghi"}:
            continue
        column = str(field.get("internal_column"))
        series = _series_for(frame, column)
        if series is None:
            continue
        values = apply_conversion(series, field.get("conversion"))
        if role in {"power_ac", "power_dc"}:
            limit = float(get_path(config, "validation.night.power_threshold_kw", 0.01))
            mask = night & (values > limit)
            message = "Power is above the configured threshold while the sun is below the night elevation threshold."
            check_id = "night_time_power"
        elif role == "energy_interval":
            limit = float(get_path(config, "validation.night.power_threshold_kw", 0.01))
            mask = night & (values > limit)
            message = "Interval energy is above the configured threshold while the sun is below the night elevation threshold."
            check_id = "night_time_energy"
        else:
            limit = float(get_path(config, "validation.night.irradiance_threshold_w_m2", 5.0))
            mask = night & (values > limit)
            message = "Irradiance is above the configured threshold while the sun is below the night elevation threshold."
            check_id = "night_time_irradiance"
        count = int(mask.fillna(False).sum())
        if count:
            checks.append(
                _check(
                    check_id,
                    "warning",
                    message,
                    count=count,
                    affected_devices=_device_values(frame, layout, mask, field),
                    time_ranges=_time_ranges(mask, frame, max_ranges),
                    details={
                        "column": field.get("source_column"),
                        "threshold": limit,
                        "sun_elevation_threshold_deg": threshold,
                        "method": "NOAA fractional-year approximation (screening only)",
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                )
            )
    if not checks:
        checks.append(
            _check(
                "night_time_generation",
                "pass",
                "No mapped power, interval-energy or irradiance reading exceeded the configured night threshold.",
                details={"sun_elevation_threshold_deg": threshold, "method": "NOAA fractional-year approximation (screening only)"},
            )
        )
    return checks


def _check_unresolved(
    fields: list[dict[str, Any]],
    timestamp_info: dict[str, Any],
    header_info: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    unresolved = [item for item in fields if item.get("unresolved")]
    if unresolved:
        checks.append(
            _check(
                "unresolved_schema_mapping",
                "warning",
                "Some source fields could not be mapped with high confidence and remain unresolved.",
                count=len(unresolved),
                details={
                    "fields": [
                        {
                            "source_column": item.get("source_column"),
                            "reasons": item.get("unresolved_reasons", []),
                        }
                        for item in unresolved
                    ]
                },
            )
        )
    if timestamp_info.get("status") != "resolved":
        checks.append(
            _check(
                "timestamp_ambiguity",
                "warning",
                "Timestamps could not be normalized to UTC with confidence.",
                details={
                    "status": timestamp_info.get("status"),
                    "reasons": timestamp_info.get("ambiguity", []),
                    "format": timestamp_info.get("format"),
                    "timezone": timestamp_info.get("timezone"),
                },
            )
        )
    if header_info.get("ambiguous"):
        checks.append(
            _check(
                "header_row_ambiguity",
                "warning",
                "Header-row detection was ambiguous; verify the selected header row.",
                details={
                    "header_row": header_info.get("header_row"),
                    "confidence": header_info.get("confidence"),
                    "candidates": header_info.get("candidates", []),
                },
            )
        )
    return checks


def validate_table(
    table: Any,
    mapping: Any = None,
    config: dict[str, Any] | None = None,
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one ingested table without modifying it."""

    config = config or load_defaults()
    frame: pd.DataFrame = table.frame if not isinstance(table, dict) else table["frame"]
    layout = (table.layout if not isinstance(table, dict) else table.get("layout", {})) or {}
    timestamp_info = (table.timestamp if not isinstance(table, dict) else table.get("timestamp", {})) or {}
    header_info = (table.header if not isinstance(table, dict) else table.get("header", {})) or {}
    fields = _mapping_fields(mapping)

    checks: list[dict[str, Any]] = []
    checks.append(_check_duplicates(frame, layout, config))
    checks.append(
        _check_order(
            frame,
            layout,
            config,
            timezone_resolved=timestamp_info.get("status") == "resolved",
        )
    )
    checks.append(_check_gaps(frame, layout, timestamp_info, config))
    checks.append(_check_missing(frame, layout, fields, config))
    checks.extend(_check_impossible(frame, layout, fields, config))
    checks.extend(_check_cumulative_resets(frame, layout, fields, config))
    checks.extend(_check_flatlines(frame, layout, fields, config))
    checks.extend(_check_night_generation(frame, layout, fields, config, timestamp_info, location))
    checks.extend(_check_unresolved(fields, timestamp_info, header_info))

    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        status = "fail"
    elif "warning" in statuses:
        status = "warning"
    else:
        status = "pass"

    limitations = []
    if timestamp_info.get("status") != "resolved":
        limitations.append("Timestamp normalization to UTC is unresolved; temporal checks are limited.")
    night_checks = [check for check in checks if check["check_id"].startswith("night_time")]
    if not night_checks or all(check["status"] == "not_checked" for check in night_checks):
        limitations.append("Night-time generation was not checked without location and resolved UTC timestamps.")
    if not fields:
        limitations.append("No schema mapping was supplied; value checks are limited to structural checks.")

    return {
        "status": status,
        "valid": status != "fail",
        "rows": int(len(frame)),
        "checks": checks,
        "counts": {
            "checks": len(checks),
            "fail": sum(1 for check in checks if check["status"] == "fail"),
            "warning": sum(1 for check in checks if check["status"] == "warning"),
            "pass": sum(1 for check in checks if check["status"] == "pass"),
            "not_checked": sum(1 for check in checks if check["status"] == "not_checked"),
        },
        "sampling_interval_seconds": timestamp_info.get("sampling_interval_seconds"),
        "limitations": limitations,
    }


def validate_frame(
    frame: pd.DataFrame,
    config: dict[str, Any] | None = None,
    timestamp_column: str | None = None,
) -> dict[str, Any]:
    """Lightweight compatibility validator for a bare DataFrame.

    It performs only structural checks that do not require guessing time zones,
    units or schema roles.  Use :func:`validate_table` after ingestion and
    mapping for the complete report.
    """

    config = config or load_defaults()
    checks: list[dict[str, Any]] = []
    rows = int(len(frame))
    timestamp_column = timestamp_column or ("timestamp" if "timestamp" in frame.columns else None)
    valid = True
    if timestamp_column and timestamp_column in frame.columns:
        raw = frame[timestamp_column].astype(str)
        duplicate_count = int(raw.duplicated(keep="first").sum())
        if duplicate_count:
            checks.append(_check("duplicate_timestamps", "fail", "Duplicate raw timestamp strings were found.", count=duplicate_count))
            valid = False
        parsed = pd.to_datetime(frame[timestamp_column], errors="coerce")
        order_count = int((parsed.diff().dt.total_seconds() < 0).sum())
        if order_count:
            checks.append(_check("out_of_order_timestamps", "fail", "Rows are not in timestamp order.", count=order_count))
            valid = False
    missing = int(frame.isna().sum().sum())
    if missing:
        checks.append(_check("missing_values", "warning", "Missing values are retained as NaN.", count=missing))
    if "power" in frame.columns:
        values = numeric_values(frame["power"])
        negative = int((values < 0).sum())
        if negative:
            checks.append(_check("negative_power", "fail", "Negative power readings were found.", count=negative))
            valid = False
    return {
        "rows": rows,
        "valid": valid,
        "status": "fail" if not valid else ("warning" if checks else "pass"),
        "checks": checks,
    }
