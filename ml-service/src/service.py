"""Public analysis service boundary.

The service is the only supported end-to-end entry point.  It wires ingestion,
schema mapping, validation, the physics baseline, anomaly detection, attribution
and the energy waterfall into one deterministic result.  It also owns input
loading, snapshot-mode gating and structured error reporting.

Contract rules enforced here:

* A missing value stays ``None``/``NaN``; it is never converted to zero.
* Actual, expected and forecast energy are independent.  None is substituted
  for another.
* Energy from power uses the actual timestamp-derived interval duration.
* Device and weather context are merged before the baseline and anomaly stages.
* Snapshot mode does not claim persistence, peer or trend evidence.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .anomaly import detect_anomalies
from .attribution import explain_interval
from .baseline import physics_baseline
from .config import get_path, json_safe, load_defaults, load_vocab
from .contract import (
    MAPPING_VERSION,
    MODEL_VERSION,
    SCHEMA_VERSION,
    build_contract,
    validate_contract,
    write_contract_json,
)
from .counterfactual import Waterfall
from .ingestion import (
    LOCAL_COLUMN,
    RAW_TIMESTAMP_COLUMN,
    ROW_ORDER_COLUMN,
    UTC_COLUMN,
    TableData,
    _detect_timestamp,
    ingest_file,
)
from .schema_mapping import (
    apply_conversion,
    detect_layout,
    map_table,
    normalize_text,
)
from .validation import validate_table

SUPPORTED_SUFFIXES = {".csv", ".xlsx"}
DEFAULT_UNITS = {
    "power": "kW",
    "energy": "kWh",
    "irradiance": "W/m2",
    "temperature": "C",
    "duration": "minutes",
}
DEVICE_COLUMNS = (
    "rated_ac_power_kw",
    "rated_dc_power_kw",
    "inverter_efficiency",
    "system_losses_fraction",
    "module_temperature_coefficient_per_c",
    "latitude_deg",
    "longitude_deg",
)
WEATHER_COLUMNS = (
    "poa_irradiance_w_m2",
    "ghi_w_m2",
    "ambient_temperature_c",
    "solar_elevation_deg",
)
OPERATING_ROLE_COLUMNS = {
    "device_id": "device_id",
    "power_ac": "ac_power_kw",
    "power_dc": "dc_power_kw",
    "energy_interval": "energy_kwh",
    "energy_cumulative": "cumulative_energy_kwh",
    "irradiance_poa": "poa_irradiance_w_m2",
    "irradiance_ghi": "ghi_w_m2",
    "ambient_temperature": "ambient_temperature_c",
    "module_temperature": "module_temperature_c",
    "capacity": "rated_ac_power_kw",
    "dc_capacity": "rated_dc_power_kw",
    "inverter_efficiency": "inverter_efficiency",
    "system_losses": "system_losses_fraction",
    "temperature_coefficient": "module_temperature_coefficient_per_c",
    "sun_elevation": "solar_elevation_deg",
    "latitude": "latitude_deg",
    "longitude": "longitude_deg",
    "availability_status": "availability_status",
}
DEVICE_ROLE_COLUMNS = {
    "device_id": "device_id",
    "capacity": "rated_ac_power_kw",
    "dc_capacity": "rated_dc_power_kw",
    "inverter_efficiency": "inverter_efficiency",
    "system_losses": "system_losses_fraction",
    "temperature_coefficient": "module_temperature_coefficient_per_c",
    "latitude": "latitude_deg",
    "longitude": "longitude_deg",
}
WEATHER_ROLE_COLUMNS = {
    "irradiance_poa": "poa_irradiance_w_m2",
    "irradiance_ghi": "ghi_w_m2",
    "ambient_temperature": "ambient_temperature_c",
    "sun_elevation": "solar_elevation_deg",
}
FORECAST_ROLE_COLUMNS = {
    "forecast_energy": "forecast_energy_kwh",
    "forecast_power": "forecast_ac_power_kw",
    "forecast_poa": "forecast_poa_irradiance_w_m2",
}
ANOMALY_EVIDENCE_KEYS = (
    "actual_power_kw",
    "expected_power_kw",
    "normalized_output",
    "poa_irradiance_w_m2",
    "peer_median",
    "peer_mad",
    "peer_z",
    "peer_persistence",
    "residual_shortfall",
    "cusum_score",
)


class AnalysisError(Exception):
    """Structured, user-safe analysis error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.details = details or {}

    def to_error(self) -> dict[str, Any]:
        return json_safe(
            {
                "code": self.code,
                "message": self.message,
                "field": self.field,
                "details": self.details,
            }
        )


@dataclass
class CanonicalTable:
    """A mapped table plus the canonical measurement columns."""

    frame: pd.DataFrame
    mapping: Any
    table: TableData
    timestamp_basis: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class InputBundle:
    """All inputs required by the analysis stages."""

    operating: CanonicalTable
    weather: CanonicalTable | None = None
    devices: CanonicalTable | None = None
    forecast: CanonicalTable | None = None
    event_log: pd.DataFrame | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    timezone: str | None = None
    interval_minutes: float | None = None
    plant_id: str | None = None


def _safe_name(value: Any) -> str:
    if value is None:
        return "<memory>"
    return Path(str(value)).name or "<memory>"


def _as_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _unique_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    seen: dict[str, int] = {}
    columns: list[str] = []
    for index, column in enumerate(result.columns):
        base = str(column).strip() or f"column_{index + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        columns.append(base if count == 0 else f"{base}__{count + 1}")
    result.columns = columns
    return result


def _raw_timestamp_text(frame: pd.DataFrame, timestamp_info: Mapping[str, Any]) -> pd.Series:
    date_column = timestamp_info.get("date_column")
    time_column = timestamp_info.get("time_column")
    if not date_column or date_column not in frame.columns:
        return pd.Series([None] * len(frame), index=frame.index, dtype=object)
    dates = frame[date_column].map(lambda value: "" if pd.isna(value) else str(value).strip())
    if time_column and time_column in frame.columns:
        times = frame[time_column].map(lambda value: "" if pd.isna(value) else str(value).strip())
        return dates.where(times.eq(""), dates + " " + times)
    return dates.where(dates.ne(""), None)


def _table_from_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    config: dict[str, Any],
    vocab: dict[str, Any],
    timezone: str | None,
) -> TableData:
    """Build an ingestion-compatible table from an in-memory DataFrame."""

    data = _unique_columns(frame.reset_index(drop=True))
    if data.empty:
        raise AnalysisError(
            "EMPTY_FILE",
            f"{name} contains no data rows.",
            details={"file": name},
        )
    labels = [str(column) for column in data.columns]
    timestamp_info = _detect_timestamp(data, labels, vocab, config, timezone)
    parsed_utc = timestamp_info.pop("_utc_series", None)
    parsed_local = timestamp_info.pop("_local_series", None)
    layout = detect_layout(data, labels, vocab, config)

    data[ROW_ORDER_COLUMN] = np.arange(len(data), dtype=int)
    data[RAW_TIMESTAMP_COLUMN] = _raw_timestamp_text(data, timestamp_info)
    if parsed_local is None:
        parsed_local = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    if parsed_utc is None:
        parsed_utc = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns, UTC]")
    data[LOCAL_COLUMN] = pd.Series(parsed_local.to_numpy(), index=data.index)
    data[UTC_COLUMN] = pd.Series(parsed_utc.to_numpy(), index=data.index)

    warnings = list(timestamp_info.get("warnings", []))
    if timestamp_info.get("status") != "resolved":
        warnings.append("Timestamp interpretation is unresolved; see timestamp.ambiguity.")

    return TableData(
        source_file=name,
        sheet_name=None,
        frame=data,
        original_columns=labels,
        raw_headers=labels,
        column_aliases={label: label for label in labels},
        header={
            "header_row": 0,
            "method": "in_memory",
            "confidence": 1.0,
            "warnings": [],
        },
        layout=layout,
        timestamp=timestamp_info,
        warnings=warnings,
    )


def _load_path(
    path: str | Path,
    *,
    config: dict[str, Any],
    vocab: dict[str, Any],
    timezone: str | None,
    sheet_name: str | None = None,
) -> tuple[TableData, list[str]]:
    path = Path(path)
    name = _safe_name(path)
    if not path.exists():
        raise AnalysisError(
            "INPUT_NOT_FOUND",
            f"Input file {name} was not found.",
            details={"file": name},
        )
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AnalysisError(
            "UNSUPPORTED_FILE_TYPE",
            f"Input file {name} has an unsupported file type; use CSV or XLSX.",
            details={"file": name, "suffix": path.suffix.lower()},
        )

    result = ingest_file(path, config=config, vocab=vocab, timezone=timezone)
    if result.errors:
        text = str(result.errors[0]).replace(str(path), name)
        lower = text.lower()
        if "does not exist" in lower:
            code = "INPUT_NOT_FOUND"
            message = f"Input file {name} was not found."
        elif "unsupported" in lower or "pdf" in lower:
            code = "UNSUPPORTED_FILE_TYPE"
            message = f"Input file {name} has an unsupported file type; use CSV or XLSX."
        else:
            code = "UNREADABLE_FILE"
            message = f"Input file {name} could not be read."
        raise AnalysisError(code, message, details={"file": name, "reason": text})

    tables = result.tables
    if not tables:
        raise AnalysisError(
            "EMPTY_FILE",
            f"Input file {name} contains no readable sheets or rows.",
            details={"file": name},
        )

    if sheet_name is not None:
        selected = next((table for table in tables if table.sheet_name == sheet_name), None)
        if selected is None:
            raise AnalysisError(
                "SHEET_NOT_FOUND",
                f"Sheet {sheet_name!r} was not found in {name}.",
                details={"file": name, "sheet_name": sheet_name},
            )
        if selected.frame.empty:
            raise AnalysisError(
                "EMPTY_FILE",
                f"Sheet {sheet_name!r} in {name} contains no data rows.",
                details={"file": name, "sheet_name": sheet_name},
            )
        return selected, list(result.warnings)

    non_empty = [table for table in tables if not table.frame.empty]
    if not non_empty:
        raise AnalysisError(
            "EMPTY_FILE",
            f"Input file {name} contains no data rows.",
            details={"file": name},
        )
    selected = non_empty[0]
    warnings = list(result.warnings)
    if len(non_empty) > 1:
        warnings.append(
            f"{name} contains multiple non-empty sheets; the first sheet was used. Supply sheet_name to choose another."
        )
    return selected, warnings


def _read_metadata(value: Any, *, name: str = "metadata") -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {}, []
    if isinstance(value, Mapping):
        return dict(value), []
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.exists():
            return {}, [f"Metadata file {_safe_name(path)} was not found."]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, [f"Metadata file {_safe_name(path)} could not be parsed."]
        return (dict(payload), []) if isinstance(payload, Mapping) else ({}, [f"Metadata file {_safe_name(path)} is not an object."])
    return {}, [f"{name} is not a mapping or JSON path."]


def _classify_directory(directory: Path) -> tuple[Path, dict[str, Path], list[str]]:
    files = [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    operating: list[Path] = []
    optional: dict[str, list[Path]] = {"weather": [], "devices": [], "forecast": [], "event_log": []}
    for path in files:
        stem = path.stem.lower()
        if "ground_truth" in stem or stem in {"manifest", "metadata"}:
            continue
        if "forecast" in stem:
            optional["forecast"].append(path)
        elif "weather" in stem:
            optional["weather"].append(path)
        elif "device" in stem:
            optional["devices"].append(path)
        elif "event" in stem:
            optional["event_log"].append(path)
        elif "operating" in stem or "operation" in stem:
            operating.append(path)
        else:
            optional.setdefault("other", []).append(path)

    warnings: list[str] = []
    if not operating:
        others = optional.get("other", [])
        if len(others) == 1:
            operating = [others[0]]
        elif len(others) > 1:
            names = ", ".join(path.name for path in others)
            raise AnalysisError(
                "AMBIGUOUS_INPUT_FILES",
                "Multiple files could be operating data; name the operating file explicitly.",
                details={"files": names},
            )
        else:
            raise AnalysisError(
                "MISSING_OPERATING_DATA",
                "No operating-data file was found in the input directory.",
                details={"directory": directory.name},
            )
    if len(operating) > 1:
        names = ", ".join(path.name for path in operating)
        raise AnalysisError(
            "AMBIGUOUS_INPUT_FILES",
            "Multiple operating-data files were found; supply the intended file explicitly.",
            details={"files": names},
        )

    chosen: dict[str, Path] = {}
    for role, paths in optional.items():
        if not paths or role == "other":
            continue
        chosen[role] = paths[0]
        if len(paths) > 1:
            warnings.append(
                f"Multiple {role} files were found; {paths[0].name} was used."
            )
    return operating[0], chosen, warnings


def _value_to_table(
    value: Any,
    *,
    name: str,
    config: dict[str, Any],
    vocab: dict[str, Any],
    timezone: str | None,
    sheet_name: str | None,
) -> tuple[TableData, list[str]]:
    if isinstance(value, pd.DataFrame):
        return _table_from_frame(value, name=name, config=config, vocab=vocab, timezone=timezone), []
    if isinstance(value, (list, tuple, Mapping)):
        return _table_from_frame(pd.DataFrame(value), name=name, config=config, vocab=vocab, timezone=timezone), []
    if isinstance(value, (str, Path)):
        return _load_path(value, config=config, vocab=vocab, timezone=timezone, sheet_name=sheet_name)
    raise AnalysisError(
        "UNREADABLE_FILE",
        f"Input {name} is not a supported path or table.",
        details={"input": name},
    )


def _resolve_metadata(
    metadata: dict[str, Any],
    *,
    timezone: str | None,
    interval_minutes: float | None,
    plant_id: str | None,
) -> tuple[str | None, float | None, str | None, dict[str, Any]]:
    resolved_timezone = timezone if timezone is not None else metadata.get("timezone")
    # The sampling interval is always derived from actual timestamps.  Metadata
    # is not allowed to override it because that would silently distort energy.
    resolved_interval = interval_minutes
    resolved_plant = plant_id or metadata.get("plant_id") or metadata.get("scenario_id")
    location: dict[str, Any] = {}
    latitude = metadata.get("latitude_deg", metadata.get("latitude"))
    longitude = metadata.get("longitude_deg", metadata.get("longitude"))
    if latitude is not None and longitude is not None:
        location = {"latitude": latitude, "longitude": longitude}
    return resolved_timezone, resolved_interval, resolved_plant, location


def _load_inputs(
    source: Any,
    *,
    config: dict[str, Any],
    vocab: dict[str, Any],
    timezone: str | None,
    interval_minutes: float | None,
    plant_id: str | None,
    sheet_name: str | None,
) -> InputBundle:
    metadata: dict[str, Any] = {}
    warnings: list[str] = []
    source_files: list[str] = []
    values: dict[str, Any] = {}

    if isinstance(source, Mapping) and any(
        key in source for key in ("operating_data", "operating", "data", "operating_path")
    ):
        metadata, metadata_warnings = _read_metadata(
            source.get("metadata", source.get("plant_context"))
        )
        warnings.extend(metadata_warnings)
        values = {
            "operating": source.get("operating_data", source.get("operating", source.get("data", source.get("operating_path")))),
            "weather": source.get("weather_data", source.get("weather")),
            "devices": source.get("device_data", source.get("devices")),
            "forecast": source.get("forecast_data", source.get("forecast")),
            "event_log": source.get("event_log", source.get("events")),
        }
        source_files = [
            _safe_name(value)
            for value in values.values()
            if isinstance(value, (str, Path))
        ] or ["<memory>"]
    elif isinstance(source, Mapping):
        metadata, metadata_warnings = _read_metadata(
            source.get("metadata", source.get("plant_context"))
        )
        warnings.extend(metadata_warnings)
        if any(key in source for key in ("metadata", "plant_context")):
            record = {key: value for key, value in source.items() if key not in {"metadata", "plant_context"}}
        else:
            record = dict(source)
        values = {"operating": pd.DataFrame([record]) if record else pd.DataFrame()}
        source_files = ["<memory>"]
    elif isinstance(source, pd.DataFrame):
        values = {"operating": source}
        source_files = ["<memory>"]
    elif isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise AnalysisError(
                "INPUT_NOT_FOUND",
                f"Input path {_safe_name(path)} was not found.",
                details={"path": _safe_name(path)},
            )
        if path.is_dir():
            metadata, metadata_warnings = _read_metadata(path / "metadata.json")
            warnings.extend(metadata_warnings)
            operating_path, optional_paths, directory_warnings = _classify_directory(path)
            warnings.extend(directory_warnings)
            values = {"operating": operating_path, **optional_paths}
            source_files = [operating_path.name] + [item.name for item in optional_paths.values()]
        else:
            values = {"operating": path}
            source_files = [path.name]
    else:
        raise AnalysisError(
            "UNREADABLE_FILE",
            "Input must be a path, DataFrame, or mapping of named inputs.",
            details={"input_type": type(source).__name__},
        )

    resolved_timezone, resolved_interval, resolved_plant, location = _resolve_metadata(
        metadata,
        timezone=timezone,
        interval_minutes=interval_minutes,
        plant_id=plant_id,
    )

    tables: dict[str, TableData] = {}
    for role, value in values.items():
        if value is None:
            continue
        try:
            table, table_warnings = _value_to_table(
                value,
                name=role if not isinstance(value, (str, Path)) else _safe_name(value),
                config=config,
                vocab=vocab,
                timezone=resolved_timezone,
                sheet_name=sheet_name,
            )
        except AnalysisError as exc:
            if role != "operating" and exc.code == "EMPTY_FILE":
                warnings.append(f"{role} input contains no data rows and was ignored.")
                continue
            raise
        tables[role] = table
        warnings.extend(table_warnings)
        # Devices and event logs do not need a resolved timestamp for their
        # role.  Reporting their timestamp ambiguity would obscure the
        # operating-data timestamp status that actually drives the analysis.
        if role not in {"devices", "event_log"}:
            warnings.extend(table.warnings)

    operating_table = tables.get("operating")
    if operating_table is None:
        raise AnalysisError(
            "MISSING_OPERATING_DATA",
            "No operating data was supplied.",
            details={},
        )

    operating_mapping = map_table(operating_table, config=config, vocab=vocab)
    operating = _canonicalize(
        operating_table,
        operating_mapping,
        OPERATING_ROLE_COLUMNS,
        plant_id=resolved_plant,
    )
    warnings.extend(operating.warnings)
    warnings.extend(operating_mapping.manifest.get("warnings", []))

    weather = None
    if "weather" in tables:
        weather_mapping = map_table(tables["weather"], config=config, vocab=vocab)
        weather = _canonicalize(
            tables["weather"],
            weather_mapping,
            WEATHER_ROLE_COLUMNS,
            plant_id=resolved_plant,
        )
        warnings.extend(weather.warnings)

    devices = None
    if "devices" in tables:
        device_mapping = map_table(tables["devices"], config=config, vocab=vocab)
        devices = _canonicalize(
            tables["devices"],
            device_mapping,
            DEVICE_ROLE_COLUMNS,
            plant_id=resolved_plant,
        )
        if "device_id" not in device_mapping.role_to_columns:
            devices.frame["device_id"] = "__plant__"
        warnings.extend(devices.warnings)

    forecast = None
    if "forecast" in tables:
        forecast_mapping = map_table(tables["forecast"], config=config, vocab=vocab)
        forecast = _canonicalize(
            tables["forecast"],
            forecast_mapping,
            FORECAST_ROLE_COLUMNS,
            plant_id=resolved_plant,
        )
        warnings.extend(forecast.warnings)

    event_log = None
    if "event_log" in tables:
        event_log, event_warnings = _canonicalize_event_log(tables["event_log"])
        warnings.extend(event_warnings)

    metadata = dict(metadata)
    if location:
        metadata.setdefault("location", location)

    return InputBundle(
        operating=operating,
        weather=weather,
        devices=devices,
        forecast=forecast,
        event_log=event_log,
        metadata=metadata,
        source_files=source_files,
        warnings=warnings,
        unresolved_fields=list(operating_mapping.unresolved_fields),
        timezone=resolved_timezone,
        interval_minutes=resolved_interval,
        plant_id=resolved_plant,
    )


def _canonicalize(
    table: TableData,
    mapping: Any,
    role_columns: Mapping[str, str],
    *,
    plant_id: str | None,
) -> CanonicalTable:
    """Rename mapped fields into stable canonical columns.

    Long/single layouts are handled row-wise.  Wide layouts with device labels in
    column headers are converted to a long frame so the rest of the pipeline sees
    one row per device and timestamp.
    """

    frame = table.frame
    fields_by_role: dict[str, list[dict[str, Any]]] = {}
    for item in mapping.fields:
        role = item.get("canonical_role")
        if role in role_columns and not item.get("unresolved"):
            fields_by_role.setdefault(str(role), []).append(item)

    utc_values = frame[UTC_COLUMN] if UTC_COLUMN in frame.columns else pd.Series(pd.NaT, index=frame.index)
    local_values = frame[LOCAL_COLUMN] if LOCAL_COLUMN in frame.columns else pd.Series(pd.NaT, index=frame.index)
    if utc_values.notna().any():
        timestamp = utc_values
        timestamp_utc = utc_values
        basis = "utc"
    elif local_values.notna().any():
        timestamp = local_values
        timestamp_utc = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
        basis = "local"
    else:
        timestamp = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        timestamp_utc = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
        basis = "unresolved"

    layout = table.layout or {}
    layout_type = str(layout.get("layout_type") or "unknown")
    labeled_fields = [
        item for items in fields_by_role.values() for item in items if item.get("device_id") is not None
    ]
    use_wide = layout_type == "wide" or (
        layout_type == "ambiguous" and not layout.get("device_column") and bool(labeled_fields)
    )

    warnings: list[str] = []
    if use_wide:
        canonical = _canonicalize_wide(
            frame,
            fields_by_role,
            role_columns,
            timestamp=timestamp,
            timestamp_utc=timestamp_utc,
            basis=basis,
            layout=layout,
            plant_id=plant_id,
        )
        if canonical.empty:
            warnings.append("Wide layout produced no canonical rows.")
    else:
        canonical = _canonicalize_long(
            frame,
            fields_by_role,
            role_columns,
            timestamp=timestamp,
            timestamp_utc=timestamp_utc,
            basis=basis,
            plant_id=plant_id,
            warnings=warnings,
        )

    if "timestamp" in canonical.columns:
        canonical = canonical.sort_values("timestamp", kind="stable", na_position="last").reset_index(drop=True)
    else:
        canonical = canonical.reset_index(drop=True)
    return CanonicalTable(
        frame=canonical,
        mapping=mapping,
        table=table,
        timestamp_basis=basis,
        warnings=warnings,
    )


def _base_canonical_columns(
    frame: pd.DataFrame,
    *,
    timestamp: pd.Series,
    timestamp_utc: pd.Series,
    basis: str,
    device_id: Any,
    plant_id: str | None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "timestamp": timestamp,
        "timestamp_utc": timestamp_utc,
        "timestamp_basis": basis,
        "device_id": device_id if device_id is not None else (plant_id or "__plant__"),
    }
    for extra in ("scenario_id", "synthetic", "plant_id"):
        if extra in frame.columns:
            base[extra] = frame[extra]
    return base


def _canonicalize_long(
    frame: pd.DataFrame,
    fields_by_role: Mapping[str, list[dict[str, Any]]],
    role_columns: Mapping[str, str],
    *,
    timestamp: pd.Series,
    timestamp_utc: pd.Series,
    basis: str,
    plant_id: str | None,
    warnings: list[str],
) -> pd.DataFrame:
    device_field = next(iter(fields_by_role.get("device_id", [])), None)
    device_values = (
        frame[device_field["internal_column"]]
        .astype(str)
        .replace({"nan": np.nan, "None": np.nan, "": np.nan})
        if device_field is not None
        else None
    )
    base = _base_canonical_columns(
        frame,
        timestamp=timestamp,
        timestamp_utc=timestamp_utc,
        basis=basis,
        device_id=device_values,
        plant_id=plant_id,
    )
    output = pd.DataFrame(base, index=frame.index)
    for role, target in role_columns.items():
        if role == "device_id":
            continue
        items = fields_by_role.get(role) or []
        if not items:
            continue
        if len(items) > 1:
            warnings.append(
                f"Multiple fields mapped to {role}; the highest-confidence field was used."
            )
        item = sorted(items, key=lambda value: (-float(value.get("confidence") or 0.0), value.get("source_column_index", 0)))[0]
        output[target] = apply_conversion(frame[item["internal_column"]], item.get("conversion"))
    output["device_id"] = output["device_id"].fillna(plant_id or "__plant__").astype(str)
    return output


def _canonicalize_wide(
    frame: pd.DataFrame,
    fields_by_role: Mapping[str, list[dict[str, Any]]],
    role_columns: Mapping[str, str],
    *,
    timestamp: pd.Series,
    timestamp_utc: pd.Series,
    basis: str,
    layout: Mapping[str, Any],
    plant_id: str | None,
) -> pd.DataFrame:
    labels = [str(label) for label in (layout.get("devices") or []) if label is not None]
    if not labels:
        labels = sorted(
            {
                str(item["device_id"])
                for items in fields_by_role.values()
                for item in items
                if item.get("device_id") is not None
            }
        )
    if not labels:
        return _canonicalize_long(
            frame,
            fields_by_role,
            role_columns,
            timestamp=timestamp,
            timestamp_utc=timestamp_utc,
            basis=basis,
            plant_id=plant_id,
            warnings=[],
        )

    parts: list[pd.DataFrame] = []
    for label in labels:
        base = _base_canonical_columns(
            frame,
            timestamp=timestamp,
            timestamp_utc=timestamp_utc,
            basis=basis,
            device_id=label,
            plant_id=plant_id,
        )
        output = pd.DataFrame(base, index=frame.index)
        for role, target in role_columns.items():
            if role == "device_id":
                continue
            items = fields_by_role.get(role) or []
            if not items:
                continue
            specific = next(
                (item for item in items if str(item.get("device_id")) == label),
                None,
            )
            generic = next(
                (item for item in items if item.get("device_id") is None),
                None,
            )
            item = specific or generic
            if item is None:
                continue
            output[target] = apply_conversion(frame[item["internal_column"]], item.get("conversion"))
        parts.append(output)
    return pd.concat(parts, ignore_index=True)


def _canonicalize_event_log(table: TableData) -> tuple[pd.DataFrame, list[str]]:
    frame = table.frame
    warnings: list[str] = []
    if frame.empty:
        return pd.DataFrame(columns=["start_utc", "end_utc", "event_type", "asset_id", "description"]), warnings

    normalized = {str(column): normalize_text(column) for column in frame.columns if not str(column).startswith("__")}

    def pick(candidates: Iterable[str], *, exclude: Iterable[str] = ()) -> str | None:
        excluded = set(exclude)
        for column, text in normalized.items():
            if column in excluded:
                continue
            if any(candidate in text for candidate in candidates):
                return column
        return None

    start = pick(("start", "from time", "begin"))
    end = pick(("end", "to time", "finish"))
    event_type = pick(("event type", "event_type", "type")) or pick(
        ("event",),
        exclude={column for column in (start, end) if column},
    )
    asset = pick(("asset id", "asset", "device id", "device", "inverter", "site", "unit"))
    description = pick(("description", "message", "comment", "reason", "note"))

    if start is None or end is None:
        warnings.append("Event log is missing start or end timestamps; event correlation is unavailable.")
        return pd.DataFrame(columns=["start_utc", "end_utc", "event_type", "asset_id", "description"]), warnings

    output = pd.DataFrame(
        {
            "start_utc": pd.to_datetime(frame[start], errors="coerce", utc=True),
            "end_utc": pd.to_datetime(frame[end], errors="coerce", utc=True),
            "event_type": frame[event_type].astype(str) if event_type else "event",
            "asset_id": frame[asset].astype(str) if asset else "",
            "description": frame[description].astype(str) if description else "",
        }
    )
    output = output.dropna(subset=["start_utc", "end_utc"]).reset_index(drop=True)
    if output.empty:
        warnings.append("Event log contained no parseable event intervals.")
    return output, warnings


def _merge_context(
    operating: pd.DataFrame,
    devices: CanonicalTable | None,
    weather: CanonicalTable | None,
) -> tuple[pd.DataFrame, list[str]]:
    frame = operating.copy().reset_index(drop=True)
    warnings: list[str] = []

    if devices is not None and not devices.frame.empty:
        device_frame = devices.frame.copy()
        device_cols = [column for column in DEVICE_COLUMNS if column in device_frame.columns]
        if device_cols:
            if "device_id" in frame.columns and "device_id" in device_frame.columns:
                keys = ["device_id"]
                if "scenario_id" in frame.columns and "scenario_id" in device_frame.columns:
                    keys = ["scenario_id", "device_id"]
                plant_only = (
                    device_frame["device_id"].astype(str).nunique() == 1
                    and str(device_frame["device_id"].iloc[0]).upper()
                    in {"__PLANT__", "PLANT", "PLANT-WIDE", "SITE"}
                )
                if plant_only:
                    # A plant-level device table has no device key to join on.
                    # Broadcast it when there is one row, or join on scenario.
                    if "scenario_id" in keys and "scenario_id" in device_frame.columns:
                        keys = ["scenario_id"]
                    elif len(device_frame) == 1:
                        for column in device_cols:
                            if column not in frame.columns:
                                frame[column] = device_frame[column].iloc[0]
                        device_cols = []
                        keys = []
                    else:
                        warnings.append(
                            "Device context is plant-level but has no scenario identifier; it was not merged."
                        )
                        keys = []
                if keys:
                    missing = [column for column in device_cols if column not in frame.columns]
                    overlap = [column for column in device_cols if column in frame.columns]
                    if missing or overlap:
                        selected = device_frame[keys + missing + overlap].drop_duplicates(
                            subset=keys, keep="first"
                        )
                        try:
                            merged = frame.merge(
                                selected,
                                on=keys,
                                how="left",
                                suffixes=("", "__device"),
                                validate="many_to_one",
                            )
                        except (ValueError, KeyError) as exc:
                            warnings.append(f"Device context could not be merged: {type(exc).__name__}.")
                        else:
                            for column in missing:
                                frame[column] = merged[column]
                            for column in overlap:
                                device_column = f"{column}__device"
                                if device_column in merged.columns:
                                    frame[column] = frame[column].where(
                                        frame[column].notna(), merged[device_column]
                                    )
            else:
                warnings.append("Device context has no matching device identifier; it was not merged.")

    if weather is not None and not weather.frame.empty:
        weather_frame = weather.frame.copy()
        weather_cols = [column for column in WEATHER_COLUMNS if column in weather_frame.columns]
        if weather_cols and "timestamp" in frame.columns and "timestamp" in weather_frame.columns:
            frame["__merge_timestamp__"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
            weather_frame["__merge_timestamp__"] = pd.to_datetime(weather_frame["timestamp"], errors="coerce", utc=True)
            keys = ["__merge_timestamp__"]
            if "scenario_id" in frame.columns and "scenario_id" in weather_frame.columns:
                keys.append("scenario_id")
            missing = [column for column in weather_cols if column not in frame.columns]
            overlap = [column for column in weather_cols if column in frame.columns]
            selected = weather_frame[keys + missing + overlap].drop_duplicates(subset=keys, keep="first")
            try:
                merged = frame.merge(selected, on=keys, how="left", suffixes=("", "__weather"))
            except (ValueError, KeyError) as exc:
                warnings.append(f"Weather context could not be merged: {type(exc).__name__}.")
                merged = frame
            for column in missing:
                frame[column] = merged[column]
            for column in overlap:
                weather_column = f"{column}__weather"
                if weather_column in merged.columns:
                    frame[column] = frame[column].where(frame[column].notna(), merged[weather_column])
            frame = frame.drop(columns=["__merge_timestamp__"], errors="ignore")
        else:
            warnings.append("Weather context has no matching timestamp; it was not merged.")

    return frame.reset_index(drop=True), warnings


def _interval_seconds_series(
    frame: pd.DataFrame,
    *,
    timestamp_column: str = "timestamp",
    device_column: str | None = "device_id",
    interval_minutes: float | None = None,
) -> pd.Series:
    if interval_minutes is not None:
        if interval_minutes <= 0:
            return pd.Series(np.nan, index=frame.index, dtype=float)
        return pd.Series(float(interval_minutes) * 60.0, index=frame.index, dtype=float)
    if timestamp_column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    timestamps = pd.to_datetime(frame[timestamp_column], errors="coerce", utc=True)
    if timestamps.isna().all():
        return pd.Series(np.nan, index=frame.index, dtype=float)
    groups = (
        frame[device_column].astype(str)
        if device_column is not None and device_column in frame.columns
        else pd.Series("__series__", index=frame.index)
    )
    working = pd.DataFrame({"ts": timestamps, "group": groups}, index=frame.index)
    previous_gap = working.groupby("group")["ts"].diff().dt.total_seconds()
    next_gap = previous_gap.groupby(working["group"]).shift(-1)
    median_gap = next_gap.groupby(working["group"]).transform("median")
    return next_gap.where(next_gap > 0.0).fillna(median_gap)


def _sampling_interval_seconds(
    frame: pd.DataFrame,
    *,
    table: TableData,
    interval_minutes: float | None,
) -> float | None:
    if interval_minutes is not None and interval_minutes > 0:
        return float(interval_minutes) * 60.0
    candidate = (table.timestamp or {}).get("sampling_interval_seconds")
    if candidate is not None:
        value = _as_float(candidate)
        if value is not None and value > 0:
            return value
    if "timestamp" not in frame.columns:
        return None
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True).dropna().drop_duplicates().sort_values()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.diff().dt.total_seconds()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return None
    value = _as_float(diffs.median())
    return value if value is not None and value > 0 else None


def _energy_component(
    value: float | None,
    *,
    status: str,
    source: str,
    completeness: float | None,
    reason: str | None,
    aggregation_period: str = "analysis_interval",
) -> dict[str, Any]:
    return {
        "value_kwh": _as_float(value),
        "status": status,
        "source": source,
        "completeness": None if completeness is None else float(max(0.0, min(1.0, completeness))),
        "aggregation_period": aggregation_period,
        "unit": "kWh",
        "reason": reason,
    }


def _unavailable_component(source: str, reason: str) -> dict[str, Any]:
    return _energy_component(
        None,
        status="unavailable",
        source=source,
        completeness=None,
        reason=reason,
    )


def _series_component(series: pd.Series, *, source: str) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce") if isinstance(series, pd.Series) else pd.Series(dtype=float)
    if values.empty or values.notna().sum() == 0:
        return _unavailable_component(source, "No valid values were available.")
    total = _as_float(values.sum(min_count=1))
    completeness = float(values.notna().mean())
    status = "available" if completeness == 1.0 else "partial"
    reason = None if status == "available" else "Some values are missing; the total covers only valid rows."
    return _energy_component(
        total,
        status=status,
        source=source,
        completeness=completeness,
        reason=reason,
    )


def _actual_energy(
    frame: pd.DataFrame,
    *,
    interval_minutes: float | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if "energy_kwh" in frame.columns:
        values = pd.to_numeric(frame["energy_kwh"], errors="coerce")
        if values.notna().sum() == 0:
            return _unavailable_component("energy_kwh", "The interval-energy column contains no valid values."), warnings
        total = _as_float(values.sum(min_count=1))
        completeness = float(values.notna().mean())
        status = "available" if completeness == 1.0 else "partial"
        reason = None if status == "available" else "Some interval-energy readings are missing."
        return (
            _energy_component(
                total,
                status=status,
                source="energy_kwh",
                completeness=completeness,
                reason=reason,
            ),
            warnings,
        )

    if "ac_power_kw" not in frame.columns:
        return _unavailable_component("energy_kwh", "Neither interval energy nor AC power was available."), warnings

    power = pd.to_numeric(frame["ac_power_kw"], errors="coerce")
    seconds = _interval_seconds_series(frame, interval_minutes=interval_minutes)
    if seconds.isna().all():
        warnings.append(
            "Actual interval duration could not be established from timestamps; actual energy is unavailable."
        )
        return _unavailable_component(
            "ac_power_kw",
            "Actual interval duration could not be established from timestamps.",
        ), warnings
    energy = power * seconds / 3600.0
    if energy.notna().sum() == 0:
        return _unavailable_component("ac_power_kw", "AC power contains no valid values."), warnings
    completeness = float(energy.notna().mean())
    status = "available" if completeness == 1.0 and seconds.notna().all() else "partial"
    if seconds.isna().any():
        warnings.append("Some interval durations could not be established; those energy values are missing.")
    reason = None if status == "available" else "Some interval durations or power readings are missing."
    return (
        _energy_component(
            _as_float(energy.sum(min_count=1)),
            status=status,
            source="ac_power_kw * actual_interval_duration",
            completeness=completeness,
            reason=reason,
        ),
        warnings,
    )


def _forecast_energy(
    frame: pd.DataFrame,
    forecast: CanonicalTable | None,
    *,
    interval_minutes: float | None,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if forecast is None or forecast.frame.empty:
        return _unavailable_component("forecast_energy_kwh", "No forecast file was supplied."), warnings

    forecast_frame = forecast.frame.copy()
    if "timestamp" not in forecast_frame.columns:
        return _unavailable_component("forecast_energy_kwh", "Forecast has no timestamp column."), warnings

    op_timestamps = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True) if "timestamp" in frame.columns else pd.Series(dtype="datetime64[ns, UTC]")
    fc_timestamps = pd.to_datetime(forecast_frame["timestamp"], errors="coerce", utc=True)
    if op_timestamps.notna().any():
        start = op_timestamps.min()
        end = op_timestamps.max()
        forecast_frame = forecast_frame.loc[fc_timestamps.between(start, end)]
        fc_timestamps = fc_timestamps.loc[forecast_frame.index]
    if forecast_frame.empty:
        return _unavailable_component(
            "forecast_energy_kwh",
            "Forecast has no rows inside the analysis interval.",
        ), warnings

    source = "forecast_energy_kwh"
    if "forecast_energy_kwh" in forecast_frame.columns:
        values = pd.to_numeric(forecast_frame["forecast_energy_kwh"], errors="coerce")
        valid_fraction = float(values.notna().mean())
        total = _as_float(values.sum(min_count=1))
    elif "forecast_ac_power_kw" in forecast_frame.columns:
        source = "forecast_ac_power_kw * actual_interval_duration"
        power = pd.to_numeric(forecast_frame["forecast_ac_power_kw"], errors="coerce")
        seconds = _interval_seconds_series(
            forecast_frame,
            device_column=None,
            interval_minutes=interval_minutes,
        )
        values = power * seconds / 3600.0
        valid_fraction = float(values.notna().mean())
        total = _as_float(values.sum(min_count=1))
    else:
        return _unavailable_component(
            "forecast_energy_kwh",
            "Forecast contains neither forecast energy nor forecast AC power.",
        ), warnings

    if total is None:
        return _unavailable_component(source, "Forecast contains no valid energy values."), warnings

    coverage: float | None = None
    op_unique = pd.Series(op_timestamps.dropna().unique()).sort_values()
    fc_unique = pd.Series(fc_timestamps.dropna().unique()).sort_values()
    if len(op_unique):
        if len(fc_unique):
            coverage = float(op_unique.isin(fc_unique).mean())
        else:
            coverage = 0.0
    minimum_coverage = float(get_path(config, "integration.minimum_forecast_coverage", 0.95))
    completeness = min(valid_fraction, coverage) if coverage is not None else valid_fraction
    if coverage is not None and coverage < minimum_coverage:
        warnings.append(
            "Forecast coverage is incomplete; the forecast total is marked partial rather than silently extrapolated."
        )
        status = "partial"
        reason = f"Forecast covers {coverage:.0%} of the analysis timestamps."
    elif valid_fraction < 1.0:
        status = "partial"
        reason = "Some forecast energy values are missing."
    else:
        status = "available"
        reason = None
    return (
        _energy_component(
            total,
            status=status,
            source=source,
            completeness=completeness,
            reason=reason,
        ),
        warnings,
    )


def _deviation_component(
    actual: Mapping[str, Any],
    forecast: Mapping[str, Any],
) -> dict[str, Any]:
    actual_value = _as_float(actual.get("value_kwh"))
    forecast_value = _as_float(forecast.get("value_kwh"))
    value = actual_value - forecast_value if actual_value is not None and forecast_value is not None else None
    if value is None:
        status = "unavailable"
        reason = "Actual or forecast energy is unavailable."
    else:
        status = "available" if actual.get("status") == "available" and forecast.get("status") == "available" else "partial"
        reason = None if status == "available" else "The deviation inherits partial actual or forecast coverage."
    actual_completeness = _as_float(actual.get("completeness"))
    forecast_completeness = _as_float(forecast.get("completeness"))
    completeness = (
        min(actual_completeness, forecast_completeness)
        if actual_completeness is not None and forecast_completeness is not None
        else None
    )
    return {
        "value_kwh": value,
        "status": status,
        "source": "actual_energy - forecast_energy",
        "completeness": completeness,
        "aggregation_period": "analysis_interval",
        "unit": "kWh",
        "reason": reason,
        "sign_convention": "actual_minus_forecast",
    }


def _expected_deviation_component(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    actual_value = _as_float(actual.get("value_kwh"))
    expected_value = _as_float(expected.get("value_kwh"))
    value = actual_value - expected_value if actual_value is not None and expected_value is not None else None
    if value is None:
        status = "unavailable"
        reason = "Actual or expected energy is unavailable."
    else:
        status = "available" if actual.get("status") == "available" and expected.get("status") == "available" else "partial"
        reason = None if status == "available" else "The performance gap inherits partial actual or expected coverage."
    actual_completeness = _as_float(actual.get("completeness"))
    expected_completeness = _as_float(expected.get("completeness"))
    completeness = (
        min(actual_completeness, expected_completeness)
        if actual_completeness is not None and expected_completeness is not None
        else None
    )
    return {
        "value_kwh": value,
        "status": status,
        "source": "actual_energy - expected_energy",
        "completeness": completeness,
        "aggregation_period": "analysis_interval",
        "unit": "kWh",
        "reason": reason,
        "sign_convention": "actual_minus_expected",
    }


def _waterfall(
    forecast: Mapping[str, Any],
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    tolerance = float(get_path(config, "integration.waterfall_tolerance_kwh", 1.0e-6))
    forecast_value = _as_float(forecast.get("value_kwh"))
    expected_value = _as_float(expected.get("value_kwh"))
    actual_value = _as_float(actual.get("value_kwh"))
    if forecast_value is None or expected_value is None or actual_value is None:
        result = Waterfall.reconcile(None, None, None, tolerance_kwh=tolerance)
        missing = []
        for label, component in (
            ("Forecast", forecast),
            ("Expected", expected),
            ("Actual", actual),
        ):
            if _as_float(component.get("value_kwh")) is None:
                reason = component.get("reason")
                missing.append(f"{label} energy: {reason}" if reason else f"{label} energy is unavailable.")
        result["reason"] = "Energy waterfall unavailable. " + " ".join(missing)
        result["limitations"] = [
            "The waterfall requires forecast, expected and actual energy.",
            *missing,
        ]
        return result

    result = Waterfall.reconcile(
        forecast_value,
        expected_value,
        actual_value,
        tolerance_kwh=tolerance,
    )
    # The arithmetic anomaly estimate is retained, but recoverability requires
    # operational/commercial evidence that this service does not have.
    result["potentially_recoverable_energy_kwh"] = None
    limitations = list(result.get("limitations", []))
    limitations.append(
        "Potentially recoverable energy is left null; it requires operational or commercial evidence."
    )
    if any(
        component.get("status") in {"partial", "unavailable"}
        for component in (forecast, expected, actual)
    ):
        result["status"] = "warning"
        limitations.append("One or more energy totals are partial; the decomposition inherits that limitation.")
    result["limitations"] = list(dict.fromkeys(limitations))
    return result


def _device_performance(
    frame: pd.DataFrame,
    *,
    baseline_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate measured and baseline energy per device without mixing assets."""
    if "device_id" not in frame.columns:
        return []
    expected_series = baseline_result.get("expected_energy_kwh")
    if not isinstance(expected_series, pd.Series):
        expected_series = pd.Series(np.nan, index=frame.index, dtype=float)
    else:
        expected_series = pd.to_numeric(expected_series.reindex(frame.index), errors="coerce")

    if "energy_kwh" in frame.columns:
        actual_series = pd.to_numeric(frame["energy_kwh"], errors="coerce")
    elif "ac_power_kw" in frame.columns:
        power = pd.to_numeric(frame["ac_power_kw"], errors="coerce")
        seconds = baseline_result.get("interval_seconds")
        if isinstance(seconds, pd.Series):
            actual_series = power * pd.to_numeric(seconds.reindex(frame.index), errors="coerce") / 3600.0
        else:
            actual_series = pd.Series(np.nan, index=frame.index, dtype=float)
    else:
        actual_series = pd.Series(np.nan, index=frame.index, dtype=float)

    result: list[dict[str, Any]] = []
    for device, indices in frame.groupby(frame["device_id"].astype(str), sort=True).groups.items():
        index = list(indices)
        actual_values = actual_series.loc[index]
        expected_values = expected_series.loc[index]
        actual_total = _as_float(actual_values.sum(min_count=1))
        expected_total = _as_float(expected_values.sum(min_count=1))
        result.append(json_safe({
            "device_id": str(device),
            "row_count": len(index),
            "actual_valid_rows": int(actual_values.notna().sum()),
            "expected_valid_rows": int(expected_values.notna().sum()),
            "actual_energy_kwh": actual_total,
            "expected_energy_kwh": expected_total,
            "deviation_kwh": actual_total - expected_total if actual_total is not None and expected_total is not None else None,
        }))
    return result


def _transform_anomalies(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for alert in alerts:
        evidence = alert.get("evidence") if isinstance(alert.get("evidence"), Mapping) else {}
        device = alert.get("device_id", alert.get("inverter_id"))
        if device is None or (isinstance(device, float) and math.isnan(device)):
            device = None
        results.append(
            json_safe(
                {
                    "timestamp_utc": alert.get("timestamp_utc"),
                    "device_id": None if device is None else str(device),
                    "status": "suspected" if alert.get("status") not in {"suspected", "confirmed"} else alert.get("status"),
                    "checks": list(alert.get("checks") or []),
                    "message": str(alert.get("message") or ""),
                    "evidence": {key: evidence.get(key) for key in ANOMALY_EVIDENCE_KEYS},
                    "missing_evidence": list(alert.get("missing_evidence") or []),
                }
            )
        )
    return results


def _attribution(
    alerts: list[dict[str, Any]],
    *,
    event_log: pd.DataFrame | None,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    hypotheses: list[dict[str, Any]] = []
    evidence: list[str] = []
    limitations: list[str] = []
    cap = int(get_path(config, "integration.max_hypotheses", 500))

    for alert in alerts:
        interval = {
            "timestamp_utc": alert.get("timestamp_utc"),
            "device_id": alert.get("device_id"),
            "status": alert.get("status"),
            "actual_power_kw": (alert.get("evidence") or {}).get("actual_power_kw"),
            "expected_power_kw": (alert.get("evidence") or {}).get("expected_power_kw"),
            "poa_irradiance_w_m2": (alert.get("evidence") or {}).get("poa_irradiance_w_m2"),
            "peer_alert": "peer_output_deviation" in set(alert.get("checks") or []),
            "residual_alert": "residual_shortfall" in set(alert.get("checks") or []),
            "cusum_alert": "residual_shortfall" in set(alert.get("checks") or []),
            "peer_z": (alert.get("evidence") or {}).get("peer_z"),
            "peer_median": (alert.get("evidence") or {}).get("peer_median"),
            "peer_mad": (alert.get("evidence") or {}).get("peer_mad"),
            "peer_persistence": (alert.get("evidence") or {}).get("peer_persistence"),
            "alert_checks": alert.get("checks") or [],
        }
        try:
            explanation = explain_interval(interval, event_log=event_log, config=config)
        except (TypeError, ValueError) as exc:
            limitations.append(f"Attribution could not explain one interval: {type(exc).__name__}.")
            continue
        for hypothesis in explanation.get("causes", []):
            if len(hypotheses) >= cap:
                limitations.append(
                    f"Hypotheses were capped at {cap}; additional alerts remain unexplained in this output."
                )
                return hypotheses, list(dict.fromkeys(evidence)), limitations
            hypotheses.append(json_safe(hypothesis))
            evidence.extend(str(item) for item in hypothesis.get("evidence", []))
        limitations.extend(str(item) for item in explanation.get("notes", []))
    return hypotheses, list(dict.fromkeys(evidence)), limitations


def _event_conflict_limitations(
    alerts: list[dict[str, Any]],
    event_log: pd.DataFrame | None,
    *,
    config: dict[str, Any],
) -> list[str]:
    if event_log is None or event_log.empty or not alerts:
        return []
    ratio_threshold = float(get_path(config, "integration.event_conflict_output_ratio", 0.80))
    notes: list[str] = []
    for alert in alerts:
        evidence = alert.get("evidence") or {}
        actual = _as_float(evidence.get("actual_power_kw"))
        expected = _as_float(evidence.get("expected_power_kw"))
        if actual is None or expected is None or expected <= 0:
            continue
        ratio = actual / expected
        if ratio < ratio_threshold:
            continue
        timestamp = pd.to_datetime(alert.get("timestamp_utc"), errors="coerce", utc=True)
        if pd.isna(timestamp):
            continue
        device = str(alert.get("device_id") or "")
        starts = pd.to_datetime(event_log["start_utc"], errors="coerce", utc=True)
        ends = pd.to_datetime(event_log["end_utc"], errors="coerce", utc=True)
        assets = event_log["asset_id"].astype(str)
        types = event_log["event_type"].astype(str)
        mask = (
            (starts <= timestamp)
            & (ends >= timestamp)
            & assets.map(lambda value: value in {"", "PLANT", "PLANT-WIDE", device})
            & types.str.lower().map(lambda value: "outage" in value or "curtail" in value)
        )
        if bool(mask.any()):
            notes.append(
                "A logged outage or curtailment overlaps an interval whose output is not below the conflict threshold; "
                "the event alone is not treated as the cause."
            )
            break
    return notes


def _data_quality(
    bundle: InputBundle,
    *,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    location = bundle.metadata.get("location") if isinstance(bundle.metadata.get("location"), Mapping) else None
    try:
        report = validate_table(
            bundle.operating.table,
            bundle.operating.mapping,
            config=config,
            location=dict(location) if location else None,
        )
    except Exception as exc:  # validation must not take down the whole analysis
        report = {
            "status": "fail",
            "valid": False,
            "rows": int(len(bundle.operating.frame)),
            "checks": [],
            "counts": {"checks": 0, "fail": 0, "warning": 0, "pass": 0, "not_checked": 0},
            "sampling_interval_seconds": None,
            "limitations": [f"Data-quality validation could not be completed: {type(exc).__name__}."],
        }
    quality = {
        "status": report.get("status", "warning"),
        "valid": bool(report.get("valid", False)),
        "rows": int(report.get("rows", len(bundle.operating.frame))),
        "checks": json_safe(report.get("checks", [])),
        "counts": {
            key: int(report.get("counts", {}).get(key, 0))
            for key in ("checks", "fail", "warning", "pass", "not_checked")
        },
        "sampling_interval_seconds": json_safe(report.get("sampling_interval_seconds")),
        "limitations": [str(item) for item in report.get("limitations", [])],
    }
    return quality, list(quality["limitations"])


def _required_fields(frame: pd.DataFrame) -> list[str]:
    missing: list[str] = []
    timestamps = pd.to_datetime(frame.get("timestamp"), errors="coerce") if "timestamp" in frame.columns else pd.Series(dtype="datetime64[ns]")
    if "timestamp" not in frame.columns or timestamps.notna().sum() == 0:
        missing.append("timestamp")
    if "ac_power_kw" not in frame.columns and "energy_kwh" not in frame.columns:
        missing.extend(["power_ac", "energy_interval"])
    if "poa_irradiance_w_m2" not in frame.columns and "ghi_w_m2" not in frame.columns:
        missing.append("irradiance_poa")
    if "rated_ac_power_kw" not in frame.columns and "rated_dc_power_kw" not in frame.columns:
        missing.append("capacity")
    return missing


def _capabilities(
    *,
    mode: str,
    frame: pd.DataFrame,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    forecast: Mapping[str, Any],
    event_log: pd.DataFrame | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce") if "timestamp" in frame.columns else pd.Series(dtype="datetime64[ns]")
    unique_timestamps = int(timestamps.dropna().nunique())
    device_count = int(frame["device_id"].nunique()) if "device_id" in frame.columns else 1
    persistence_n = int(get_path(config, "anomaly.persistence_n", 2))
    peer_min = int(get_path(config, "anomaly.peer_min_devices", 3))

    def item(status: str, reason: str | None = None) -> dict[str, Any]:
        return {"status": status, "reason": reason}

    if mode == "snapshot":
        persistence = item("not_applicable", "Snapshot mode has only one timestamp.")
        peer = item("not_applicable", "Snapshot mode has only one timestamp.")
        trend = item("not_applicable", "Snapshot mode has only one timestamp.")
    else:
        persistence = (
            item("available")
            if unique_timestamps >= persistence_n + 1
            else item("unavailable", f"At least {persistence_n + 1} timestamps per series are required.")
        )
        peer = (
            item("available")
            if device_count >= peer_min and unique_timestamps >= 2
            else item("unavailable", f"At least {peer_min} same-time devices and two timestamps are required.")
        )
        trend = (
            item("available")
            if unique_timestamps >= 3
            else item("unavailable", "At least three timestamps are required.")
        )

    event_available = event_log is not None and not event_log.empty
    event = item("available") if event_available else item("unavailable", "No usable event log was supplied.")
    waterfall_available = all(
        _as_float(component.get("value_kwh")) is not None
        for component in (forecast, expected, actual)
    )
    waterfall = (
        item("available")
        if waterfall_available
        else item("unavailable", "Forecast, expected and actual energy are required.")
    )
    return {
        "basic_validation": item("available"),
        "baseline": item("available") if _as_float(expected.get("value_kwh")) is not None else item("unavailable", "Expected energy is unavailable."),
        "persistence": persistence,
        "peer_comparison": peer,
        "trend_analysis": trend,
        "event_correlation": event,
        "energy_waterfall": waterfall,
    }


def _conversion_text(conversion: Mapping[str, Any] | None) -> str | None:
    if not isinstance(conversion, Mapping):
        return None
    source, target = conversion.get("from_unit"), conversion.get("to_unit")
    if conversion.get("operation") == "identity":
        return f"{source} (no conversion)"
    factor, offset = conversion.get("factor", 1.0), conversion.get("offset", 0.0)
    rule = f"x {factor:g}" + (f" {offset:+g}" if offset else "")
    return f"{source} -> {target} ({rule})"


def _column_mapping(bundle: InputBundle) -> list[dict[str, Any]]:
    """Expose the auditable mapping manifest for every supplied input table."""

    rows: list[dict[str, Any]] = []
    for name in ("operating", "weather", "devices", "forecast"):
        table = getattr(bundle, name, None)
        mapping = getattr(table, "mapping", None)
        for item in getattr(mapping, "fields", None) or []:
            confidence = _as_float(item.get("confidence"))
            reasons = [str(reason) for reason in item.get("unresolved_reasons") or []]
            reasons += [str(warning) for warning in item.get("warnings") or []
                        if warning and "no numeric values available" not in str(warning)]
            rows.append({
                "input": name,
                "source_file": item.get("source_file"),
                "sheet_name": item.get("sheet_name"),
                "source_column": str(item.get("source_column")),
                "canonical_role": item.get("canonical_role"),
                "device_id": None if item.get("device_id") is None else str(item.get("device_id")),
                "detected_unit": item.get("detected_unit"),
                "canonical_unit": item.get("canonical_unit"),
                "conversion": _conversion_text(item.get("conversion")),
                "confidence": confidence,
                "used": bool(item.get("canonical_role")) and not item.get("unresolved"),
                "reasons": list(dict.fromkeys(reasons)),
            })
    return rows


def _quality_issue_reason(quality: Mapping[str, Any]) -> str | None:
    status = quality.get("status")
    if status == "pass":
        return None
    if status == "fail":
        return "Data quality status is fail."
    material: list[str] = []
    for check in quality.get("checks", []) or []:
        if check.get("status") not in {"warning", "fail"}:
            continue
        if check.get("check_id") == "unresolved_schema_mapping":
            # Unmapped extra columns are preserved and reported, but they do not
            # limit the analysis. Missing required roles are reported separately
            # through missing_required_fields and already make the result partial.
            continue
        material.append(str(check.get("check_id") or "unknown_check"))
    if not material:
        return None
    return "Data quality warnings: " + ", ".join(dict.fromkeys(material)) + "."


def _status_and_reasons(
    *,
    mode: str,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    forecast: Mapping[str, Any],
    quality: Mapping[str, Any],
    missing_required: list[str],
    capabilities: Mapping[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if mode == "snapshot":
        reasons.append("Snapshot mode cannot establish persistence, peer comparison or trend evidence.")
    if actual.get("status") != "available":
        reasons.append("Actual energy is unavailable or partial.")
    if expected.get("status") != "available":
        reasons.append("Expected energy is unavailable or partial.")
    if forecast.get("status") != "available":
        reasons.append("Forecast energy is unavailable or partial.")
    quality_reason = _quality_issue_reason(quality)
    if quality_reason:
        reasons.append(quality_reason)
    if missing_required:
        reasons.append("Missing required inputs: " + ", ".join(missing_required) + ".")
    # Peer and trend checks are optional capabilities; their absence is
    # reported in ``capabilities`` but does not make a complete energy and
    # anomaly analysis partial.  Persistence is part of the anomaly evidence.
    persistence = capabilities.get("persistence", {})
    if persistence.get("status") == "unavailable":
        reasons.append("Persistence analysis is unavailable.")
    return ("partial" if reasons else "success"), list(dict.fromkeys(reasons))


def _summary(
    *,
    status: str,
    mode: str,
    frame: pd.DataFrame,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    forecast: Mapping[str, Any],
    reasons: list[str],
) -> str:
    def amount(component: Mapping[str, Any]) -> str:
        value = _as_float(component.get("value_kwh"))
        return "unavailable" if value is None else f"{value:.2f} kWh"

    devices = int(frame["device_id"].nunique()) if "device_id" in frame.columns else 1
    text = (
        f"{mode.capitalize()} analysis covered {len(frame)} rows across {devices} device(s): "
        f"actual {amount(actual)}, expected {amount(expected)}, forecast {amount(forecast)}."
    )
    if status == "partial" and reasons:
        text += " Partial because " + "; ".join(reason.rstrip(".") for reason in reasons) + "."
    return text


def _default_capabilities(reason: str) -> dict[str, Any]:
    return {
        key: {"status": "unavailable", "reason": reason}
        for key in (
            "basic_validation",
            "baseline",
            "persistence",
            "peer_comparison",
            "trend_analysis",
            "event_correlation",
            "energy_waterfall",
        )
    }


def _default_quality(*, status: str = "fail", rows: int = 0, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "valid": status != "fail",
        "rows": int(rows),
        "checks": [],
        "counts": {"checks": 0, "fail": 0, "warning": 0, "pass": 0, "not_checked": 0},
        "sampling_interval_seconds": None,
        "limitations": [reason] if reason else [],
    }


def _error_payload(
    error: AnalysisError,
    *,
    status: str,
    mode: str,
    request: Mapping[str, Any],
    config: dict[str, Any],
    vocab: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    forecast = _unavailable_component("forecast_energy_kwh", "Analysis did not complete.")
    expected = _unavailable_component("physics_baseline", "Analysis did not complete.")
    actual = _unavailable_component("energy_kwh", "Analysis did not complete.")
    waterfall = _waterfall(forecast, expected, actual, config=config)
    waterfall["reason"] = "Analysis did not complete."
    quality = _default_quality(reason=reason or error.message)
    payload = build_contract(
        analysis_status=status,
        analysis_mode="snapshot" if mode == "snapshot" else "full",
        summary=reason or error.message,
        request=dict(request),
        interval={
            "start_utc": None,
            "end_utc": None,
            "timezone": request.get("timezone"),
            "timestamp_basis": "unresolved",
            "duration_minutes": None,
            "sampling_interval_seconds": None,
            "device_count": 0,
            "row_count": 0,
        },
        energy={
            "forecast": forecast,
            "expected": expected,
            "actual": actual,
            "deviation": _deviation_component(actual, forecast),
        },
        forecast_energy=None,
        expected_energy=None,
        actual_energy=None,
        deviation=None,
        expected_deviation=_expected_deviation_component(actual, expected),
        expected_deviation_kwh=None,
        waterfall=waterfall,
        anomalies=[],
        hypotheses=[],
        evidence=[],
        limitations=[reason or error.message],
        unresolved_fields=[],
        missing_required_fields=[],
        data_quality=quality,
        capabilities=_default_capabilities("Analysis did not complete."),
        units=dict(DEFAULT_UNITS),
        model_version=MODEL_VERSION,
        mapping_version=MAPPING_VERSION,
        config_version=str(config.get("config_version", "")),
        vocab_version=str(vocab.get("vocab_version", "")),
        method="none",
        model_status="not_available",
        errors=[error.to_error()],
    ).to_dict()
    return json_safe(payload)


def _analyze_bundle(
    bundle: InputBundle,
    *,
    mode_requested: str,
    config: dict[str, Any],
    vocab: dict[str, Any],
) -> dict[str, Any]:
    operating_frame = bundle.operating.frame
    context, context_warnings = _merge_context(
        operating_frame,
        bundle.devices,
        bundle.weather,
    )
    warnings = list(bundle.warnings) + context_warnings

    # A single analysis represents one plant operating scenario. Combining
    # multiple scenario IDs would silently add independent simulations into
    # the same energy totals and peer comparisons, so fail with an actionable
    # validation error instead of returning misleading aggregate metrics.
    if "scenario_id" in context.columns:
        scenario_ids = context["scenario_id"].dropna().astype(str).str.strip()
        scenario_ids = scenario_ids[scenario_ids.ne("")].unique().tolist()
        if len(scenario_ids) > 1:
            raise AnalysisError(
                "MULTIPLE_SCENARIOS_UNSUPPORTED",
                "This upload contains multiple scenario IDs. Upload one scenario at a time so energy totals and inverter comparisons are not mixed.",
                field="scenario_id",
                details={"scenario_ids": scenario_ids[:20], "scenario_count": len(scenario_ids)},
            )

    # Keep the source's synthetic-data marker visible in the final report.
    # Synthetic scenarios are useful for integration checks, not real-world
    # prediction-accuracy claims.
    if "synthetic" in context.columns:
        synthetic = context["synthetic"].astype(str).str.strip().str.lower().isin(
            {"true", "1", "yes", "y"}
        )
        if synthetic.any() and synthetic.all():
            warnings.append(
                "All source records are marked synthetic; use this result for integration validation, not real-world accuracy claims."
            )
        elif synthetic.any():
            warnings.append(
                "The source mixes synthetic and non-synthetic records; interpret metrics with this data-quality limitation."
            )

    timestamps = (
        pd.to_datetime(context["timestamp"], errors="coerce")
        if "timestamp" in context.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    unique_timestamps = int(timestamps.dropna().nunique())
    snapshot_threshold = int(get_path(config, "integration.snapshot_max_timestamps", 1))
    if mode_requested == "snapshot":
        mode = "snapshot"
    elif mode_requested == "full" and unique_timestamps > snapshot_threshold:
        mode = "full"
    elif unique_timestamps <= snapshot_threshold:
        mode = "snapshot"
        if mode_requested == "full":
            warnings.append("Full analysis was requested but only one timestamp is available; snapshot mode was used.")
    else:
        mode = "full"

    quality, quality_limitations = _data_quality(bundle, config=config)
    warnings.extend(quality_limitations)

    baseline_result = physics_baseline(
        context,
        config=config,
        poa_column="poa_irradiance_w_m2" if "poa_irradiance_w_m2" in context.columns else None,
        ghi_column="ghi_w_m2" if "ghi_w_m2" in context.columns else None,
        module_temperature_column="module_temperature_c" if "module_temperature_c" in context.columns else None,
        ambient_temperature_column="ambient_temperature_c" if "ambient_temperature_c" in context.columns else None,
        capacity_column="rated_ac_power_kw" if "rated_ac_power_kw" in context.columns else None,
        dc_capacity_column="rated_dc_power_kw" if "rated_dc_power_kw" in context.columns else None,
        inverter_efficiency_column="inverter_efficiency" if "inverter_efficiency" in context.columns else None,
        system_losses_column="system_losses_fraction" if "system_losses_fraction" in context.columns else None,
        temperature_coefficient_column="module_temperature_coefficient_per_c" if "module_temperature_coefficient_per_c" in context.columns else None,
        timestamp_column="timestamp",
        device_column="device_id",
        sampling_interval_minutes=bundle.interval_minutes,
    )
    warnings.extend(baseline_result.get("warnings", []))
    expected_component = _series_component(
        baseline_result.get("expected_energy_kwh", pd.Series(dtype=float)),
        source="physics_baseline",
    )
    device_performance = _device_performance(context, baseline_result=baseline_result)
    actual_component, actual_warnings = _actual_energy(
        context,
        interval_minutes=bundle.interval_minutes,
    )
    warnings.extend(actual_warnings)
    forecast_component, forecast_warnings = _forecast_energy(
        context,
        bundle.forecast,
        interval_minutes=bundle.interval_minutes,
        config=config,
    )
    warnings.extend(forecast_warnings)
    deviation_component = _deviation_component(actual_component, forecast_component)
    expected_deviation_component = _expected_deviation_component(actual_component, expected_component)
    waterfall = _waterfall(forecast_component, expected_component, actual_component, config=config)

    anomalies: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    evidence: list[str] = []
    if mode == "full":
        anomaly_result = detect_anomalies(
            context,
            config=config,
            expected_power_kw=baseline_result.get("expected_power_kw"),
            actual_column="ac_power_kw" if "ac_power_kw" in context.columns else None,
            device_column="device_id" if "device_id" in context.columns else None,
            timestamp_column="timestamp",
            poa_column="poa_irradiance_w_m2" if "poa_irradiance_w_m2" in context.columns else None,
            solar_elevation_column="solar_elevation_deg" if "solar_elevation_deg" in context.columns else None,
            capacity_column="rated_ac_power_kw" if "rated_ac_power_kw" in context.columns else None,
        )
        warnings.extend(anomaly_result.get("limitations", []))
        anomalies = _transform_anomalies(anomaly_result.get("alerts", []))
        if anomalies:
            hypotheses, evidence, attribution_limitations = _attribution(
                anomalies,
                event_log=bundle.event_log,
                config=config,
            )
            warnings.extend(attribution_limitations)
        else:
            warnings.append("No anomaly alerts were raised; no cause hypotheses were generated.")
    else:
        warnings.append(
            "Snapshot mode skipped persistence, peer comparison, trend analysis and anomaly alerts."
        )

    warnings.extend(_event_conflict_limitations(anomalies, bundle.event_log, config=config))
    if bundle.event_log is not None and not bundle.event_log.empty and not anomalies:
        warnings.append("An event log was supplied, but no anomaly alert interval was available for correlation.")

    missing_required = _required_fields(context)
    capabilities = _capabilities(
        mode=mode,
        frame=context,
        expected=expected_component,
        actual=actual_component,
        forecast=forecast_component,
        event_log=bundle.event_log,
        config=config,
    )
    analysis_status, reasons = _status_and_reasons(
        mode=mode,
        actual=actual_component,
        expected=expected_component,
        forecast=forecast_component,
        quality=quality,
        missing_required=missing_required,
        capabilities=capabilities,
    )

    errors: list[dict[str, Any]] = []
    timestamp_status = (bundle.operating.table.timestamp or {}).get("status")
    if timestamp_status != "resolved":
        analysis_status = "partial"
        reasons.append("Operating timestamps could not be normalized with confidence.")
        errors.append(
            {
                "code": "AMBIGUOUS_TIMESTAMP",
                "message": "Operating timestamps could not be normalized with confidence.",
                "field": "timestamp",
                "details": json_safe(
                    {
                        "status": timestamp_status,
                        "ambiguity": (bundle.operating.table.timestamp or {}).get("ambiguity", []),
                    }
                ),
            }
        )

    if "timestamp" in context.columns and timestamps.notna().any():
        start_value = timestamps.min()
        end_value = timestamps.max()
        duration = _as_float((end_value - start_value).total_seconds() / 60.0)
    else:
        start_value = None
        end_value = None
        duration = None
    sampling_seconds = _sampling_interval_seconds(
        context,
        table=bundle.operating.table,
        interval_minutes=bundle.interval_minutes,
    )
    device_count = int(context["device_id"].nunique()) if "device_id" in context.columns else 0

    request = {
        "plant_id": bundle.plant_id,
        "source_files": list(dict.fromkeys(bundle.source_files)),
        "timezone": bundle.timezone,
        "interval_minutes": bundle.interval_minutes,
        "mode_requested": mode_requested,
    }
    interval = {
        "start_utc": json_safe(start_value),
        "end_utc": json_safe(end_value),
        "timezone": bundle.timezone,
        "timestamp_basis": bundle.operating.timestamp_basis,
        "duration_minutes": duration,
        "sampling_interval_seconds": sampling_seconds,
        "device_count": device_count,
        "row_count": int(len(context)),
    }
    if bundle.operating.timestamp_basis == "local":
        warnings.append(
            "Timestamps are reported on a local basis because the UTC time zone could not be resolved."
        )

    if bundle.unresolved_fields:
        warnings.append(
            "Columns not mapped to a supported field were preserved but not used in the analysis: "
            + ", ".join(dict.fromkeys(str(item) for item in bundle.unresolved_fields)) + "."
        )
    limitations = list(dict.fromkeys(str(item) for item in warnings if item))
    summary = _summary(
        status=analysis_status,
        mode=mode,
        frame=context,
        actual=actual_component,
        expected=expected_component,
        forecast=forecast_component,
        reasons=reasons,
    )
    payload = build_contract(
        analysis_status=analysis_status,
        analysis_mode=mode,
        summary=summary,
        request=request,
        interval=interval,
        device_performance=device_performance,
        energy={
            "forecast": forecast_component,
            "expected": expected_component,
            "actual": actual_component,
            "deviation": deviation_component,
        },
        forecast_energy=_as_float(forecast_component.get("value_kwh")),
        expected_energy=_as_float(expected_component.get("value_kwh")),
        actual_energy=_as_float(actual_component.get("value_kwh")),
        deviation=_as_float(deviation_component.get("value_kwh")),
        expected_deviation=expected_deviation_component,
        expected_deviation_kwh=_as_float(expected_deviation_component.get("value_kwh")),
        waterfall=waterfall,
        anomalies=anomalies,
        hypotheses=hypotheses,
        evidence=evidence,
        limitations=limitations,
        unresolved_fields=list(dict.fromkeys(bundle.unresolved_fields)),
        missing_required_fields=missing_required,
        data_quality=quality,
        capabilities=capabilities,
        units=dict(DEFAULT_UNITS),
        model_version=MODEL_VERSION,
        mapping_version=MAPPING_VERSION,
        config_version=str(config.get("config_version", "")),
        vocab_version=str(vocab.get("vocab_version", "")),
        method="physics_baseline",
        model_status="physics_baseline_active",
        errors=errors,
        column_mapping=_column_mapping(bundle),
    ).to_dict()
    return json_safe(payload)


def analyze(
    source: Any,
    *,
    config: dict[str, Any] | None = None,
    output_path: str | Path | None = None,
    mode: str = "auto",
    timezone: str | None = None,
    interval_minutes: float | None = None,
    plant_id: str | None = None,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """Analyze one plant/scenario and return a contract-v2 payload.

    ``source`` may be a scenario directory, a single CSV/XLSX file, a DataFrame,
    or a mapping with keys such as ``operating_data``, ``weather_data``,
    ``device_data``, ``forecast_data``, ``event_log`` and ``metadata``.
    """

    config = config or load_defaults()
    vocab = load_vocab()
    if mode not in {"auto", "snapshot", "full"}:
        error = AnalysisError(
            "INVALID_ARGUMENT",
            "mode must be one of: auto, snapshot, full.",
            field="mode",
            details={"mode": str(mode)},
        )
        request = {
            "plant_id": plant_id,
            "source_files": [_safe_name(source)] if isinstance(source, (str, Path)) else ["<memory>"],
            "timezone": timezone,
            "interval_minutes": interval_minutes,
            "mode_requested": "auto",
        }
        payload = _error_payload(
            error,
            status="invalid_input",
            mode="full",
            request=request,
            config=config,
            vocab=vocab,
        )
        validate_contract(payload)
        if output_path is not None:
            write_contract_json(payload, output_path)
        return payload

    request = {
        "plant_id": plant_id,
        "source_files": [_safe_name(source)] if isinstance(source, (str, Path)) else ["<memory>"],
        "timezone": timezone,
        "interval_minutes": interval_minutes,
        "mode_requested": mode,
    }
    try:
        bundle = _load_inputs(
            source,
            config=config,
            vocab=vocab,
            timezone=timezone,
            interval_minutes=interval_minutes,
            plant_id=plant_id,
            sheet_name=sheet_name,
        )
        request.update(
            {
                "plant_id": bundle.plant_id,
                "source_files": list(dict.fromkeys(bundle.source_files)),
                "timezone": bundle.timezone,
                "interval_minutes": bundle.interval_minutes,
            }
        )
        payload = _analyze_bundle(
            bundle,
            mode_requested=mode,
            config=config,
            vocab=vocab,
        )
    except AnalysisError as exc:
        payload = _error_payload(
            exc,
            status="invalid_input",
            mode=mode if mode in {"snapshot", "full"} else "full",
            request=request,
            config=config,
            vocab=vocab,
        )
    except Exception as exc:  # never leak an unhandled stack trace to a client
        error = AnalysisError(
            "INTERNAL_ERROR",
            "An internal error occurred while analyzing the input.",
            details={"error_type": type(exc).__name__},
        )
        payload = _error_payload(
            error,
            status="failed",
            mode=mode if mode in {"snapshot", "full"} else "full",
            request=request,
            config=config,
            vocab=vocab,
            reason="Analysis failed before a result could be produced.",
        )

    try:
        validate_contract(payload)
    except Exception:
        # A schema bug must not turn into an unstructured exception for clients.
        error = AnalysisError(
            "INTERNAL_ERROR",
            "The analysis output did not satisfy the versioned contract.",
        )
        payload = _error_payload(
            error,
            status="failed",
            mode=mode if mode in {"snapshot", "full"} else "full",
            request=request,
            config=config,
            vocab=vocab,
            reason="The analysis output did not satisfy the versioned contract.",
        )
        validate_contract(payload)

    if output_path is not None:
        write_contract_json(payload, output_path)
    return payload
