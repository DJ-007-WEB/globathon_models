"""Physics-based expected PV power and interval-energy baseline.

The baseline is deliberately deterministic.  It uses plane-of-array (POA)
irradiance when available, an explicit GHI proxy only when the caller allows it,
system capacity, configured losses and inverter efficiency.

Power model (documented simplification)::

    p_dc_kw = rated_dc_kw * (poa_w_m2 / 1000)
              * (1 + gamma * (module_temp_c - 25))
              * (1 - system_losses_fraction)

    p_ac_kw = min(p_dc_kw * inverter_efficiency, rated_ac_kw)

Required inputs are irradiance and AC/DC capacity.  Missing required inputs or
unclear units produce explicit warnings and NaN estimates rather than invented
values.  GHI is never silently substituted for POA.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import get_path, load_defaults

BASELINE_VERSION = "1.0.0"

POA_CANDIDATES = ("poa_irradiance_w_m2", "irradiance_poa", "poa_w_m2", "poa")
GHI_CANDIDATES = ("ghi_w_m2", "irradiance_ghi", "ghi_wm2", "ghi")
MODULE_TEMP_CANDIDATES = (
    "module_temperature_c",
    "module_temp_c",
    "module_temperature",
    "temp_mod_c",
)
AMBIENT_TEMP_CANDIDATES = (
    "ambient_temperature_c",
    "ambient_temp_c",
    "ambient_temperature",
)
CAPACITY_CANDIDATES = (
    "rated_ac_power_kw",
    "capacity_kw",
    "ac_capacity_kw",
    "rated_capacity_kw",
    "capacity",
)
DC_CAPACITY_CANDIDATES = (
    "rated_dc_power_kw",
    "dc_capacity_kw",
    "rated_dc_kw",
)
EFFICIENCY_CANDIDATES = ("inverter_efficiency", "efficiency")
LOSSES_CANDIDATES = (
    "system_losses_fraction",
    "system_losses",
    "losses_fraction",
)
GAMMA_CANDIDATES = (
    "module_temperature_coefficient_per_c",
    "temperature_coefficient_per_c",
    "gamma",
)
TIMESTAMP_CANDIDATES = (
    "timestamp_utc",
    "__timestamp_utc__",
    "__timestamp_local__",
    "timestamp",
)
DEVICE_CANDIDATES = ("inverter_id", "device_id")


def _mapping_lookup(mapping: Any | None) -> tuple[dict[str, str], dict[str, str | None]]:
    """Return role -> column and role -> unit from a mapping result/manifest."""

    if mapping is None:
        return {}, {}
    fields = getattr(mapping, "fields", None)
    if fields is None and isinstance(mapping, Mapping):
        fields = mapping.get("fields", [])
    columns: dict[str, str] = {}
    units: dict[str, str | None] = {}
    for field in fields or []:
        role = field.get("canonical_role")
        column = field.get("internal_column")
        if not role or not column or field.get("unresolved"):
            continue
        if role not in columns:
            columns[str(role)] = str(column)
            units[str(role)] = field.get("detected_unit")
    return columns, units


def _find_column(
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


def _infer_unit(column: str | None, kind: str) -> str | None:
    if column is None:
        return None
    text = str(column).lower().replace("²", "2").replace("^", "")
    if kind == "irradiance":
        if "kw/m2" in text or "kw_m2" in text:
            return "kW/m2"
        if "w/m2" in text or "w_m2" in text or "wm2" in text:
            return "W/m2"
    elif kind == "power":
        if "mw" in text:
            return "MW"
        if "kw" in text:
            return "kW"
        if "w" in text:
            return "W"
    elif kind == "temperature":
        if "_f" in text or "fahrenheit" in text:
            return "F"
        if "_k" in text or "kelvin" in text:
            return "K"
        if "_c" in text or "celsius" in text:
            return "C"
    return None


def _normalize_unit(value: str | None, kind: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("²", "2").replace("^", "")
    text = text.replace(" ", "").replace("_", "/")
    if kind == "irradiance":
        if text in {"w/m2", "w/m-2", "wm-2", "wm2"}:
            return "W/m2"
        if text in {"kw/m2", "kw/m-2", "kwm2"}:
            return "kW/m2"
    elif kind == "power":
        if text in {"w", "watt", "watts", "wp"}:
            return "W"
        if text in {"kw", "kilowatt", "kilowatts", "kwp"}:
            return "kW"
        if text in {"mw", "megawatt", "megawatts", "mwp"}:
            return "MW"
    elif kind == "temperature":
        if text in {"c", "degc", "celsius", "°c"}:
            return "C"
        if text in {"f", "degf", "fahrenheit", "°f"}:
            return "F"
        if text in {"k", "kelvin"}:
            return "K"
    return None


def _as_series(value: float | int | pd.Series | np.ndarray | None, index: pd.Index) -> pd.Series | None:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        return pd.to_numeric(value.reindex(index), errors="coerce")
    if np.isscalar(value):
        return pd.Series(float(value), index=index, dtype=float)
    return pd.to_numeric(pd.Series(value, index=index), errors="coerce")


def _convert_irradiance(series: pd.Series, unit: str | None) -> pd.Series:
    if unit == "W/m2":
        return series
    if unit == "kW/m2":
        return series * 1000.0
    return series.where(False)


def _convert_power(series: pd.Series, unit: str | None) -> pd.Series:
    if unit == "kW":
        return series
    if unit == "W":
        return series / 1000.0
    if unit == "MW":
        return series * 1000.0
    return series.where(False)


def _convert_temperature(series: pd.Series, unit: str | None) -> pd.Series:
    if unit == "C":
        return series
    if unit == "F":
        return (series - 32.0) * 5.0 / 9.0
    if unit == "K":
        return series - 273.15
    return series.where(False)


def _interval_seconds(
    frame: pd.DataFrame,
    timestamp_column: str | None,
    device_column: str | None,
    sampling_interval_minutes: float | None,
) -> tuple[pd.Series, list[str]]:
    warnings: list[str] = []
    index = frame.index
    if sampling_interval_minutes is not None:
        if sampling_interval_minutes <= 0:
            warnings.append("sampling_interval_minutes must be positive.")
            return pd.Series(np.nan, index=index), warnings
        return pd.Series(float(sampling_interval_minutes) * 60.0, index=index), warnings
    if timestamp_column is None or timestamp_column not in frame.columns:
        warnings.append(
            "Timestamp or sampling interval is unavailable; energy is not calculated."
        )
        return pd.Series(np.nan, index=index), warnings

    timestamps = pd.to_datetime(frame[timestamp_column], errors="coerce", utc=True)
    if timestamps.isna().all():
        warnings.append("Timestamps could not be parsed; energy is not calculated.")
        return pd.Series(np.nan, index=index), warnings
    groups = (
        frame[device_column].astype(str)
        if device_column is not None and device_column in frame.columns
        else pd.Series("__series__", index=index)
    )
    working = pd.DataFrame({"ts": timestamps, "group": groups}, index=index)
    previous_gap = working.groupby("group")["ts"].diff().dt.total_seconds()
    next_gap = previous_gap.groupby(working["group"]).shift(-1)
    median_gap = next_gap.groupby(working["group"]).transform("median")
    seconds = next_gap.where(next_gap > 0.0).fillna(median_gap)
    if seconds.isna().all():
        warnings.append(
            "Actual interval duration could not be established from timestamps; energy is not calculated."
        )
    elif seconds.isna().any():
        warnings.append(
            "Some interval durations could not be established; those energy values are missing."
        )
    return seconds, warnings


def physics_baseline(
    frame: pd.DataFrame,
    *,
    mapping: Any | None = None,
    config: dict[str, Any] | None = None,
    poa_column: str | None = None,
    ghi_column: str | None = None,
    module_temperature_column: str | None = None,
    ambient_temperature_column: str | None = None,
    capacity_column: str | None = None,
    dc_capacity_column: str | None = None,
    inverter_efficiency_column: str | None = None,
    system_losses_column: str | None = None,
    temperature_coefficient_column: str | None = None,
    timestamp_column: str | None = None,
    device_column: str | None = None,
    capacity_kw: float | pd.Series | np.ndarray | None = None,
    dc_capacity_kw: float | pd.Series | np.ndarray | None = None,
    inverter_efficiency: float | pd.Series | None = None,
    system_losses: float | pd.Series | None = None,
    temperature_coefficient_per_c: float | pd.Series | None = None,
    sampling_interval_minutes: float | None = None,
    irradiance_unit: str | None = None,
    temperature_unit: str | None = None,
    capacity_unit: str | None = None,
    allow_ghi_proxy: bool | None = None,
) -> dict[str, Any]:
    """Estimate expected AC power and interval energy with explicit warnings."""

    config = config or load_defaults()
    mapping_columns, mapping_units = _mapping_lookup(mapping)
    warnings: list[str] = []
    index = frame.index

    poa_name = _find_column(
        frame, poa_column, POA_CANDIDATES, "irradiance_poa", mapping_columns
    )
    ghi_name = _find_column(
        frame, ghi_column, GHI_CANDIDATES, "irradiance_ghi", mapping_columns
    )
    module_name = _find_column(
        frame,
        module_temperature_column,
        MODULE_TEMP_CANDIDATES,
        "module_temperature",
        mapping_columns,
    )
    ambient_name = _find_column(
        frame,
        ambient_temperature_column,
        AMBIENT_TEMP_CANDIDATES,
        "ambient_temperature",
        mapping_columns,
    )
    capacity_name = _find_column(
        frame, capacity_column, CAPACITY_CANDIDATES, "capacity", mapping_columns
    )
    dc_capacity_name = _find_column(
        frame,
        dc_capacity_column,
        DC_CAPACITY_CANDIDATES,
        "dc_capacity",
        mapping_columns,
    )
    efficiency_name = _find_column(
        frame,
        inverter_efficiency_column,
        EFFICIENCY_CANDIDATES,
        "inverter_efficiency",
        mapping_columns,
    )
    losses_name = _find_column(
        frame,
        system_losses_column,
        LOSSES_CANDIDATES,
        "system_losses",
        mapping_columns,
    )
    gamma_name = _find_column(
        frame,
        temperature_coefficient_column,
        GAMMA_CANDIDATES,
        "temperature_coefficient",
        mapping_columns,
    )
    timestamp_name = _find_column(
        frame, timestamp_column, TIMESTAMP_CANDIDATES, "timestamp", mapping_columns
    )
    device_name = _find_column(
        frame, device_column, DEVICE_CANDIDATES, "device_id", mapping_columns
    )

    poa_unit = _normalize_unit(
        irradiance_unit if irradiance_unit is not None else mapping_units.get("irradiance_poa"),
        "irradiance",
    ) or _infer_unit(poa_name, "irradiance")
    ghi_unit = _normalize_unit(
        irradiance_unit if irradiance_unit is not None else mapping_units.get("irradiance_ghi"),
        "irradiance",
    ) or _infer_unit(ghi_name, "irradiance")
    temperature_unit_normalized = _normalize_unit(temperature_unit, "temperature")
    module_unit = (
        temperature_unit_normalized
        or _normalize_unit(mapping_units.get("module_temperature"), "temperature")
        or _infer_unit(module_name, "temperature")
    )
    ambient_unit = (
        temperature_unit_normalized
        or _normalize_unit(mapping_units.get("ambient_temperature"), "temperature")
        or _infer_unit(ambient_name, "temperature")
    )
    capacity_unit_normalized = _normalize_unit(capacity_unit, "power")
    ac_unit = (
        capacity_unit_normalized
        or _normalize_unit(mapping_units.get("capacity"), "power")
        or _infer_unit(capacity_name, "power")
    )
    dc_unit = (
        capacity_unit_normalized
        or _normalize_unit(mapping_units.get("dc_capacity"), "power")
        or _infer_unit(dc_capacity_name, "power")
    )

    if poa_name is not None:
        poa = _convert_irradiance(
            pd.to_numeric(frame[poa_name], errors="coerce"), poa_unit
        )
        irradiance_basis = "poa"
        if poa_unit is None:
            warnings.append(
                f"Irradiance unit for {poa_name!r} is unclear; expected power is unavailable."
            )
    elif ghi_name is not None:
        proxy_allowed = (
            bool(get_path(config, "baseline.allow_ghi_proxy", False))
            if allow_ghi_proxy is None
            else bool(allow_ghi_proxy)
        )
        if proxy_allowed:
            poa = _convert_irradiance(
                pd.to_numeric(frame[ghi_name], errors="coerce"), ghi_unit
            )
            irradiance_basis = "ghi_proxy"
            warnings.append(
                f"POA is unavailable; GHI column {ghi_name!r} is used only as an explicit proxy."
            )
            if ghi_unit is None:
                warnings.append(
                    f"Irradiance unit for {ghi_name!r} is unclear; expected power is unavailable."
                )
        else:
            poa = None
            irradiance_basis = None
            warnings.append(
                "POA irradiance is unavailable and GHI proxy use is disabled; expected power is unavailable. "
                "Supply plane-of-array (POA/GTI) irradiance, or set baseline.allow_ghi_proxy: true to accept "
                "a GHI-based estimate with an explicit warning."
            )
    else:
        poa = None
        irradiance_basis = None
        warnings.append("No POA or GHI irradiance column was found; expected power is unavailable.")

    if poa is not None:
        negative = poa < 0.0
        if bool(negative.any()):
            warnings.append("Negative irradiance values were clipped to zero.")
        poa = poa.clip(lower=0.0)
        if bool(poa.isna().all()):
            warnings.append(
                "The irradiance column contains no valid values; expected power is unavailable."
            )
        elif bool(poa.isna().any()):
            warnings.append(
                "Some irradiance values are missing; expected power is unavailable for those rows."
            )

    if capacity_name is not None:
        ac_capacity = _convert_power(
            pd.to_numeric(frame[capacity_name], errors="coerce"), ac_unit
        )
        if ac_unit is None:
            warnings.append(
                f"Capacity unit for {capacity_name!r} is unclear; expected power is unavailable."
            )
    elif capacity_kw is not None:
        ac_capacity = _as_series(capacity_kw, index)
    else:
        ac_capacity = None
        warnings.append("AC capacity is unavailable; expected power is unavailable.")

    if ac_capacity is not None:
        ac_capacity = ac_capacity.where(ac_capacity > 0.0)
        if ac_capacity.isna().all():
            warnings.append("AC capacity is missing or non-positive; expected power is unavailable.")
        elif ac_capacity.isna().any():
            warnings.append(
                "Some AC capacity values are missing or non-positive; expected power is unavailable for those rows."
            )

    if dc_capacity_name is not None:
        dc_capacity = _convert_power(
            pd.to_numeric(frame[dc_capacity_name], errors="coerce"), dc_unit
        )
        if dc_unit is None:
            warnings.append(
                f"DC capacity unit for {dc_capacity_name!r} is unclear; configured DC/AC ratio is used."
            )
            dc_capacity = None
    elif dc_capacity_kw is not None:
        dc_capacity = _as_series(dc_capacity_kw, index)
    else:
        dc_capacity = None

    dc_ac_ratio = float(get_path(config, "baseline.dc_ac_ratio", 1.2))
    if dc_capacity is None and ac_capacity is not None:
        dc_capacity = ac_capacity * dc_ac_ratio
        warnings.append(
            "DC capacity is unavailable; a configured DC/AC ratio is used for expected power."
        )
    if dc_capacity is not None:
        dc_capacity = dc_capacity.where(dc_capacity > 0.0)
        if dc_capacity.isna().all():
            warnings.append(
                "DC capacity is missing or non-positive; expected power is unavailable."
            )
        elif dc_capacity.isna().any():
            warnings.append(
                "Some DC capacity values are missing or non-positive; expected power is unavailable for those rows."
            )

    efficiency_default = float(
        get_path(config, "baseline.inverter_efficiency", 0.97)
    )
    if efficiency_name is not None:
        efficiency = pd.to_numeric(frame[efficiency_name], errors="coerce")
    else:
        efficiency = _as_series(
            inverter_efficiency if inverter_efficiency is not None else efficiency_default,
            index,
        )
    if efficiency is not None:
        if bool((efficiency > 1.0).any()):
            warnings.append("Inverter efficiency values above 1.0 were clipped to 1.0.")
        efficiency = efficiency.clip(lower=0.0, upper=1.0)

    losses_default = float(get_path(config, "baseline.system_losses_fraction", 0.12))
    if losses_name is not None:
        losses = pd.to_numeric(frame[losses_name], errors="coerce")
    else:
        losses = _as_series(
            system_losses if system_losses is not None else losses_default, index
        )
    if losses is not None:
        if bool(((losses < 0.0) | (losses >= 1.0)).any()):
            warnings.append("System losses outside [0, 1) were clipped.")
        losses = losses.clip(lower=0.0, upper=0.99)

    gamma_default = float(
        get_path(config, "baseline.temperature_coefficient_per_c", -0.0035)
    )
    if gamma_name is not None:
        gamma = pd.to_numeric(frame[gamma_name], errors="coerce")
    else:
        gamma = _as_series(
            temperature_coefficient_per_c
            if temperature_coefficient_per_c is not None
            else gamma_default,
            index,
        )

    module_temp = None
    if module_name is not None and module_unit is not None:
        module_temp = _convert_temperature(
            pd.to_numeric(frame[module_name], errors="coerce"), module_unit
        )
    elif module_name is not None:
        warnings.append(
            f"Module-temperature unit for {module_name!r} is unclear; it was not used."
        )

    if (module_temp is None or module_temp.isna().all()) and ambient_name is not None:
        if ambient_unit is None:
            warnings.append(
                f"Ambient-temperature unit for {ambient_name!r} is unclear; module temperature is not estimated."
            )
        elif poa is not None:
            ambient = _convert_temperature(
                pd.to_numeric(frame[ambient_name], errors="coerce"), ambient_unit
            )
            k = float(
                get_path(config, "baseline.module_temperature_k_c_per_w_m2", 0.03)
            )
            module_temp = ambient + k * poa
            warnings.append(
                "Module temperature was estimated from ambient temperature and irradiance."
            )

    if module_temp is not None and module_temp.isna().any():
        if ambient_name is not None and ambient_unit is not None and poa is not None:
            ambient = _convert_temperature(
                pd.to_numeric(frame[ambient_name], errors="coerce"), ambient_unit
            )
            k = float(
                get_path(config, "baseline.module_temperature_k_c_per_w_m2", 0.03)
            )
            module_temp = module_temp.fillna(ambient + k * poa)
            warnings.append(
                "Missing module temperatures were estimated from ambient temperature and irradiance."
            )

    if module_temp is None or module_temp.isna().all():
        module_temp = pd.Series(25.0, index=index)
        warnings.append(
            "Module and ambient temperature are unavailable; a 25 C reference temperature is used."
        )
    else:
        if bool(module_temp.isna().any()):
            warnings.append(
                "Some module temperatures were missing; a 25 C reference temperature is used for those rows."
            )
        module_temp = module_temp.fillna(25.0)

    reference = float(get_path(config, "baseline.irradiance_reference_w_m2", 1000.0))
    if poa is None or ac_capacity is None or dc_capacity is None:
        expected_power = pd.Series(np.nan, index=index)
    else:
        temperature_factor = 1.0 + gamma * (module_temp - 25.0)
        temperature_factor = temperature_factor.clip(lower=0.0)
        dc_power = (
            dc_capacity
            * (poa / reference)
            * temperature_factor
            * (1.0 - losses)
        )
        dc_power = dc_power.clip(lower=0.0)
        expected_power = np.minimum(dc_power * efficiency, ac_capacity)
        expected_power = expected_power.clip(lower=0.0)

    interval_seconds, interval_warnings = _interval_seconds(
        frame, timestamp_name, device_name, sampling_interval_minutes
    )
    warnings.extend(interval_warnings)
    expected_energy = expected_power * interval_seconds / 3600.0

    valid_power = int(expected_power.notna().sum())
    valid_energy = int(expected_energy.notna().sum())
    if valid_power == 0:
        status = "unavailable"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    baseline_mean = (
        float(expected_power.mean()) if valid_power else None
    )
    return {
        "baseline_version": BASELINE_VERSION,
        "status": status,
        "rows": int(len(frame)),
        "valid_rows": valid_power,
        "valid_energy_rows": valid_energy,
        "baseline": baseline_mean,
        "expected_power_kw": expected_power.rename("expected_power_kw"),
        "expected_energy_kwh": expected_energy.rename("expected_energy_kwh"),
        "interval_seconds": interval_seconds.rename("interval_seconds"),
        "module_temperature_c": module_temp.rename("module_temperature_c"),
        "irradiance_basis": irradiance_basis,
        "warnings": warnings,
        "columns": {
            "poa": poa_name,
            "ghi": ghi_name,
            "module_temperature": module_name,
            "ambient_temperature": ambient_name,
            "capacity": capacity_name,
            "dc_capacity": dc_capacity_name,
            "inverter_efficiency": efficiency_name,
            "system_losses": losses_name,
            "temperature_coefficient": gamma_name,
            "timestamp": timestamp_name,
            "device_id": device_name,
        },
        "units": {
            "poa": poa_unit,
            "ghi": ghi_unit,
            "module_temperature": module_unit,
            "ambient_temperature": ambient_unit,
            "capacity": ac_unit,
            "dc_capacity": dc_unit,
        },
        "assumptions": {
            "irradiance_reference_w_m2": reference,
            "dc_ac_ratio": dc_ac_ratio,
            "inverter_efficiency": efficiency_default,
            "system_losses_fraction": losses_default,
            "temperature_coefficient_per_c": gamma_default,
        },
    }


def residual_model(frame: pd.DataFrame, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Placeholder for the optional LightGBM residual model.

    The physics baseline remains the final method unless a held-out run shows a
    meaningful improvement.  This function intentionally does not fabricate a
    model or a metric.
    """

    return {
        "rows": int(len(frame)),
        "residuals": 0.0,
        "status": "not_available",
        "available": False,
        "warnings": [
            "LightGBM residual model was not fitted; physics baseline remains the final method."
        ],
    }
