"""Deterministic schema mapping and mapping-manifest generation.

The mapper never guesses a plant-specific meaning.  It scores headers against
``configs/schema_vocab.yaml``, adds value/range evidence, and records every
accepted or unresolved field in a manifest.  A bare magnitude is never used to
infer a unit, and ambiguous day/month order or time zone is left unresolved by
the ingestion layer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .config import get_path, json_safe, load_defaults, load_vocab

MAPPING_VERSION = "1.0.0"

NUMERIC_ROLES = {
    "power_ac",
    "power_dc",
    "energy_interval",
    "energy_cumulative",
    "irradiance_poa",
    "irradiance_ghi",
    "irradiance_dni",
    "irradiance_dhi",
    "cloud_cover",
    "dc_ac_ratio",
    "ambient_temperature",
    "module_temperature",
    "capacity",
    "dc_capacity",
    "inverter_efficiency",
    "system_losses",
    "temperature_coefficient",
    "sun_elevation",
    "latitude",
    "longitude",
    "forecast",
    "forecast_energy",
    "forecast_power",
    "forecast_poa",
}
MEASUREMENT_ROLES = {
    "power_ac",
    "power_dc",
    "energy_interval",
    "energy_cumulative",
    "irradiance_poa",
    "irradiance_ghi",
    "ambient_temperature",
    "module_temperature",
    "forecast",
    "forecast_energy",
    "forecast_power",
    "forecast_poa",
}
DEDUPE_ROLES = MEASUREMENT_ROLES | {"capacity", "dc_capacity"}
UNIT_FAMILY_ROLES = {
    "power_ac": "power",
    "power_dc": "power",
    "energy_interval": "energy",
    "energy_cumulative": "energy",
    "irradiance_poa": "irradiance",
    "irradiance_ghi": "irradiance",
    "irradiance_dni": "irradiance",
    "irradiance_dhi": "irradiance",
    "ambient_temperature": "temperature",
    "module_temperature": "temperature",
    "capacity": "capacity",
    "dc_capacity": "capacity",
    "forecast_energy": "energy",
    "forecast_power": "power",
    "forecast_poa": "irradiance",
}
# Roles measuring the same quantity as power or as energy; the unit decides which.
UNIT_PAIRED_ROLES = {
    "power_ac": "energy_interval",
    "energy_interval": "power_ac",
    "forecast_power": "forecast_energy",
    "forecast_energy": "forecast_power",
}
# The generic "forecast" role is resolved to a concrete forecast role by unit.
FORECAST_UNIT_ROLES = ("forecast_power", "forecast_energy", "forecast_poa")
# Per-device columns in wide layouts that are not measurements but still belong
# to one device (e.g. State_INV1).
DEVICE_LABELLED_ROLES = MEASUREMENT_ROLES | {"capacity", "availability_status"}

GENERIC_DEVICE_LABELS = {
    "device",
    "unit",
    "inverter",
    "string",
    "array",
    "meter",
    "channel",
    "equipment",
    "asset",
    "source",
}
# Roles that only apply when the header says the value is a forecast/design value.
ROLE_REQUIRED_TOKENS: dict[str, set[str]] = {
    role: {"forecast", "forecasted", "predicted", "prediction", "expected", "design", "planned",
           "projected", "projection", "estimated", "simulated", "budget", "target"}
    for role in ("forecast", "forecast_energy", "forecast_power", "forecast_poa")
}

ROLE_NEGATIVE_TOKENS: dict[str, set[str]] = {
    "device_id": {
        "type",
        "category",
        "kind",
        "class",
        "model",
        "manufacturer",
        "make",
        "efficiency",
        "power",
        "voltage",
        "current",
        "temperature",
        "temp",
        "energy",
        "frequency",
        "factor",
        "status",
        "state",
        "availability",
        "capacity",
        "irradiance",
        "revenue",
        "tariff",
        "rate",
        "flag",
    },
    "timestamp": {"interval", "duration", "elapsed", "minutes", "minute", "seconds", "hours"},
    "power_ac": {"reactive", "apparent", "factor", "voltage", "current", "frequency", "efficiency", "energy", "yield", "temperature", "irradiance", "rated", "capacity", "nameplate", "installed", "nominal", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "power_dc": {"reactive", "apparent", "factor", "voltage", "current", "frequency", "efficiency", "energy", "yield", "temperature", "irradiance", "rated", "capacity", "nameplate", "installed", "nominal", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "energy_interval": {"power", "reactive", "factor", "voltage", "current", "frequency", "efficiency", "temperature", "irradiance", "cumulative", "total", "lifetime", "meter", "running", "aggregate", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "energy_cumulative": {"power", "reactive", "factor", "voltage", "current", "frequency", "efficiency", "temperature", "irradiance", "interval", "period", "per", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "irradiance_poa": {"power", "energy", "voltage", "current", "frequency", "temperature", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "irradiance_ghi": {"power", "energy", "voltage", "current", "frequency", "temperature", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "ambient_temperature": {"power", "energy", "voltage", "current", "frequency", "efficiency", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "module_temperature": {"power", "energy", "voltage", "current", "frequency", "efficiency", "coefficient", "forecast", "predicted", "expected", "design", "planned", "projected"},
    "capacity": {"factor", "temperature", "irradiance", "voltage", "current", "dc"},
    "dc_capacity": {"factor", "temperature", "irradiance", "voltage", "current", "ac"},
    "forecast": {"energy", "power", "poa", "irradiance", "temperature", "ghi", "dni", "dhi"},
}


def normalize_text(value: Any) -> str:
    """Normalize header text without removing meaningful unit characters."""

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("&", " and ")
    text = text.replace("²", "2").replace("³", "3").replace("°", "deg")
    text = re.sub(r"[^a-z0-9/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value).lower())


def tokenize(value: Any) -> list[str]:
    normalized = normalize_text(value)
    return [token for token in re.split(r"[^a-z0-9]+", normalized) if token]


def _alias_score(normalized: str, tokens: set[str], alias: str) -> float:
    alias_norm = normalize_text(alias)
    if not alias_norm:
        return 0.0
    alias_tokens = set(tokenize(alias))
    if normalized == alias_norm:
        return 1.0
    if not alias_tokens:
        return 0.0
    if alias_tokens.issubset(tokens):
        coverage = len(alias_tokens) / max(len(tokens), 1)
        score = 0.80 + 0.10 * coverage
        # Generic one-word aliases are weaker when the header has other words.
        if len(alias_tokens) == 1 and len(tokens) > 1 and alias_norm in {"time", "date", "ts", "meter", "source", "unit"}:
            score *= 0.70
        return score
    if tokens.issubset(alias_tokens):
        return 0.68
    if len(alias_norm) >= 4 and re.search(r"(?<![a-z0-9])" + re.escape(alias_norm) + r"(?![a-z0-9])", normalized):
        return 0.66
    return 0.0


def score_header_roles(header: Any, vocab: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return role candidates for a header, highest score first."""

    normalized = normalize_text(header)
    tokens = set(tokenize(header))
    roles = vocab.get("roles", {})
    fuzzy_min_len = int(get_path(config, "mapping.fuzzy_min_alias_length", 4))
    fuzzy_min_ratio = float(get_path(config, "mapping.fuzzy_min_ratio", 0.84))
    candidates: list[dict[str, Any]] = []
    for role, spec in roles.items():
        best_score = 0.0
        best_alias = None
        for alias in spec.get("aliases", []):
            score = _alias_score(normalized, tokens, alias)
            if score > best_score:
                best_score = score
                best_alias = alias
        if best_score == 0.0 and len(normalized) >= fuzzy_min_len:
            alias_norm = normalized
            for alias in spec.get("aliases", []):
                ratio = SequenceMatcher(None, alias_norm, normalize_text(alias)).ratio()
                if ratio >= fuzzy_min_ratio and len(normalize_text(alias)) >= fuzzy_min_len:
                    score = 0.72 * ratio
                    if score > best_score:
                        best_score = score
                        best_alias = alias
        negative_tokens = ROLE_NEGATIVE_TOKENS.get(role, set())
        if best_score > 0 and negative_tokens.intersection(tokens):
            best_score *= 0.25
        required_tokens = ROLE_REQUIRED_TOKENS.get(role)
        if best_score > 0 and required_tokens and not required_tokens.intersection(tokens):
            best_score *= 0.25
        if best_score > 0:
            candidates.append(
                {
                    "role": role,
                    "score": round(min(best_score, 1.0), 4),
                    "matched_alias": best_alias,
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["role"]))
    return candidates


def _unit_aliases(vocab: dict[str, Any], family: str) -> list[tuple[str, str]]:
    units = vocab.get("units", {}).get(family, {})
    aliases = units.get("aliases", {})
    pairs: list[tuple[str, str]] = []
    for canonical, values in aliases.items():
        for alias in values:
            pairs.append((canonical, str(alias)))
    # Prefer longer aliases so kWh is matched before kW and kWp before kW.
    pairs.sort(key=lambda item: len(compact_text(item[1])), reverse=True)
    return pairs


def infer_header_unit(header: Any, role: str | None, vocab: dict[str, Any]) -> tuple[str | None, str | None]:
    """Infer a unit from the header text only.

    Returns ``(canonical_unit, evidence)``.  If no unit token is present the
    unit is ``None``; magnitude is never used to fill the gap.
    """

    family = UNIT_FAMILY_ROLES.get(role or "")
    if family is None:
        return None, None
    normalized = normalize_text(header)
    compact = compact_text(header)
    tokens = set(tokenize(header))
    for canonical, alias in _unit_aliases(vocab, family):
        alias_norm = normalize_text(alias)
        alias_compact = compact_text(alias)
        if not alias_compact:
            continue
        if " " in alias_norm or "/" in alias_norm:
            if re.search(r"(?<![a-z0-9])" + re.escape(alias_norm) + r"(?![a-z0-9])", normalized):
                return canonical, f"header contains unit '{alias}'"
            if alias_compact in compact:
                return canonical, f"header contains unit '{alias}'"
        else:
            if alias_compact in tokens:
                return canonical, f"header contains unit '{alias}'"
            if re.search(r"(?<![a-z0-9])" + re.escape(alias_compact) + r"(?![a-z0-9])", compact):
                return canonical, f"header contains unit '{alias}'"
    return None, None


def unit_conversion(role: str | None, unit: str | None, vocab: dict[str, Any]) -> dict[str, Any] | None:
    """Return a conversion descriptor from ``unit`` to the role's canonical unit."""

    family = UNIT_FAMILY_ROLES.get(role or "")
    if family is None or unit is None:
        return None
    units = vocab.get("units", {}).get(family, {})
    canonical = units.get("canonical")
    if canonical is None:
        return None
    if unit == canonical:
        return {
            "operation": "identity",
            "factor": 1.0,
            "offset": 0.0,
            "from_unit": unit,
            "to_unit": canonical,
        }

    factor = 1.0
    offset = 0.0
    if family == "power":
        factor = {"W": 0.001, "kW": 1.0, "MW": 1000.0}.get(unit, 1.0)
    elif family == "energy":
        factor = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}.get(unit, 1.0)
    elif family == "irradiance":
        factor = {"W/m2": 1.0, "kW/m2": 1000.0}.get(unit, 1.0)
    elif family == "temperature":
        if unit == "F":
            factor = 5.0 / 9.0
            offset = -32.0 * 5.0 / 9.0
    elif family == "capacity":
        factor = {"Wp": 0.001, "kWp": 1.0, "MWp": 1000.0, "kW": 1.0, "MW": 1000.0}.get(unit, 1.0)

    return {
        "operation": "multiply_add",
        "factor": float(factor),
        "offset": float(offset),
        "from_unit": unit,
        "to_unit": canonical,
    }


def numeric_values(series: pd.Series) -> pd.Series:
    """Convert a series to numeric while preserving missing values as NaN."""

    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = series.map(lambda value: value.strip() if isinstance(value, str) else value)
    return pd.to_numeric(cleaned, errors="coerce")


def apply_conversion(series: pd.Series, conversion: dict[str, Any] | None) -> pd.Series:
    values = numeric_values(series)
    if conversion:
        values = values * float(conversion.get("factor", 1.0)) + float(conversion.get("offset", 0.0))
    return values


def _numeric_ratio(series: pd.Series) -> float:
    non_null = series.notna() & (series.astype(str).str.strip() != "")
    if not non_null.any():
        return 0.0
    return float(numeric_values(series[non_null]).notna().mean())


def _value_evidence(series: pd.Series, role: str, config: dict[str, Any]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    if role in NUMERIC_ROLES:
        ratio = _numeric_ratio(series)
        if ratio < 0.35:
            warnings.append(f"only {ratio:.0%} of non-null values are numeric")
            return -0.30, warnings
        if ratio < 0.80:
            warnings.append(f"{ratio:.0%} of non-null values are numeric")
            return -0.10, warnings
        return 0.05, warnings
    if role in {"timestamp", "device_id", "availability_status", "event_description", "event_start", "event_end"}:
        non_null = int(series.notna().sum())
        if non_null == 0:
            warnings.append("column has no non-null values")
            return -0.20, warnings
        return 0.02, warnings
    return 0.0, warnings


def _conversion_for(role: str, unit: str | None, vocab: dict[str, Any]) -> dict[str, Any] | None:
    return unit_conversion(role, unit, vocab)


def _range_validation(
    role: str,
    values: pd.Series,
    config: dict[str, Any],
    capacity_kw: float | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    numeric = pd.to_numeric(values, errors="coerce")
    non_null = numeric.dropna()
    if non_null.empty:
        return "not_checked", checks, ["no numeric values available for range validation"]

    plaus = config.get("plausibility", {})
    failures = 0

    def add(name: str, mask: pd.Series, message: str, severity: str = "warning") -> None:
        nonlocal failures
        count = int(mask.fillna(False).sum())
        if count:
            checks.append({"check": name, "status": "fail" if severity == "fail" else "warning", "count": count, "message": message})
            warnings.append(f"{message}: {count} value(s)")
            if severity == "fail":
                failures += 1

    if role in {"power_ac", "power_dc"}:
        min_power = float(plaus.get("power_min_kw", 0.0))
        if not bool(plaus.get("allow_negative_power", False)):
            add("negative_power", numeric < min_power, f"{role} below the configured minimum")
        if capacity_kw is not None and capacity_kw > 0:
            limit = capacity_kw * float(plaus.get("capacity_tolerance_ratio", 1.2))
            add("power_above_capacity", numeric > limit, f"{role} above documented capacity tolerance")
    elif role in {"irradiance_poa", "irradiance_ghi"}:
        add("irradiance_below_min", numeric < float(plaus.get("irradiance_min_w_m2", 0.0)), "irradiance below configured minimum", "warning")
        add("irradiance_above_max", numeric > float(plaus.get("irradiance_max_w_m2", 1500.0)), "irradiance above configured maximum", "fail")
    elif role == "ambient_temperature":
        add("ambient_temperature_out_of_range", (numeric < float(plaus.get("ambient_temperature_min_c", -50.0))) | (numeric > float(plaus.get("ambient_temperature_max_c", 70.0))), "ambient temperature outside configured range", "fail")
    elif role == "module_temperature":
        add("module_temperature_out_of_range", (numeric < float(plaus.get("module_temperature_min_c", -50.0))) | (numeric > float(plaus.get("module_temperature_max_c", 100.0))), "module temperature outside configured range", "fail")
    elif role in {"energy_interval", "energy_cumulative"}:
        if not bool(plaus.get("allow_negative_power", False)):
            add("negative_energy", numeric < float(plaus.get("energy_min_kwh", 0.0)), f"{role} below the configured minimum", "warning")
        if role == "energy_cumulative":
            reset_count = int((numeric.diff() < -float(config.get("validation", {}).get("cumulative_reset_tolerance", 1e-9))).sum())
            if reset_count:
                checks.append({"check": "cumulative_reset", "status": "warning", "count": reset_count, "message": "cumulative counter decreases"})
                warnings.append(f"cumulative counter decreases: {reset_count} value(s)")
    elif role == "capacity":
        add("capacity_nonpositive", numeric <= float(plaus.get("capacity_min_kw", 0.0)), "capacity is not positive", "fail")

    status = "fail" if failures else ("warning" if checks else "pass")
    return status, checks, warnings


def _role_unit_required(role: str, config: dict[str, Any]) -> bool:
    roles = set(get_path(config, "mapping.unit_required_roles", []))
    return role in roles and UNIT_FAMILY_ROLES.get(role) is not None


def _field_validation(
    role: str,
    series: pd.Series,
    unit: str | None,
    conversion: dict[str, Any] | None,
    config: dict[str, Any],
    capacity_kw: float | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    values = apply_conversion(series, conversion)
    status, range_checks, range_warnings = _range_validation(role, values, config, capacity_kw=capacity_kw)
    checks.extend(range_checks)
    warnings.extend(range_warnings)
    if role in NUMERIC_ROLES and _numeric_ratio(series) < 0.35:
        status = "fail"
        checks.append({"check": "numeric_parse", "status": "fail", "count": int(series.notna().sum()), "message": "too few numeric values for a numeric role"})
        warnings.append("too few numeric values for a numeric role")
    if _role_unit_required(role, config) and unit is None:
        status = "fail"
        checks.append({"check": "unit_missing", "status": "fail", "count": 0, "message": "unit is required but was not established from the header"})
        warnings.append("unit cannot be established from header text; magnitude alone is not used")
    return status, {"status": status, "checks": checks}, warnings


def _extract_device_label(header: Any, vocab: dict[str, Any]) -> str | None:
    tokens = tokenize(header)
    if not tokens:
        return None
    stopwords = {normalize_text(item) for item in vocab.get("device_label_stopwords", [])}
    role_tokens: set[str] = set()
    for role_name, spec in vocab.get("roles", {}).items():
        if role_name == "device_id":
            continue
        for alias in spec.get("aliases", []):
            role_tokens.update(tokenize(alias))
    for family in vocab.get("units", {}).values():
        for values in family.get("aliases", {}).values():
            for alias in values:
                role_tokens.update(tokenize(alias))
    remaining = [
        token
        for token in tokens
        if token not in stopwords and token not in role_tokens and token not in {"and", "of", "the", "per"}
    ]
    if not remaining:
        return None
    # Keep device-type words such as inv/inverter/meter when they are attached
    # to an identifier; they prevent collisions between different equipment.
    label = "-".join(remaining) if any(re.search(r"\d", token) for token in remaining) else " ".join(remaining)
    if label in GENERIC_DEVICE_LABELS:
        return None
    # Keep the source spelling (INV1, not inv1) so labels join to device sheets.
    pattern = r"[^A-Za-z0-9]*".join(re.escape(part) for part in re.split(r"[- ]", label) if part)
    original = re.search(pattern, str(header), re.IGNORECASE) if pattern else None
    return original.group(0) if original else label


def _reconcile_role_with_unit(
    role: str | None, unit: str | None, unit_text: str, vocab: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    """Let an explicit unit decide between power and energy (and resolve generic forecasts).

    A column named like a power series but labelled kWh is interval energy, and the
    reverse; a generic "forecast" column becomes forecast power, energy or POA from
    its unit. Without a unit token nothing changes, so magnitude is never used.
    """
    if role == "forecast":
        for candidate in FORECAST_UNIT_ROLES:
            candidate_unit, _ = infer_header_unit(unit_text, candidate, vocab)
            if candidate_unit:
                return candidate, candidate_unit, f"Generic forecast column resolved to {candidate} from its unit."
        return role, unit, None
    paired = UNIT_PAIRED_ROLES.get(role or "")
    if paired is None:
        return role, unit, None
    own_family = UNIT_FAMILY_ROLES.get(role or "")
    paired_unit, _ = infer_header_unit(unit_text, paired, vocab)
    if paired_unit and own_family == "power" and unit in {None, *vocab.get("units", {}).get("energy", {}).get("aliases", {})}:
        # e.g. "kWh" also contains "kW": an energy unit wins for a power-named column.
        return paired, paired_unit, f"Unit {paired_unit} indicates {paired}, not {role}."
    if paired_unit and unit is None:
        return paired, paired_unit, f"Unit {paired_unit} indicates {paired}, not {role}."
    return role, unit, None


def detect_layout(
    frame: pd.DataFrame,
    original_columns: Iterable[str] | None,
    vocab: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Detect long (device column) versus wide (device in headers) layouts."""

    columns = list(frame.columns)
    originals = list(original_columns) if original_columns is not None else columns
    minimum = float(get_path(config, "mapping.minimum_candidate_score", 0.52))
    max_devices = int(get_path(config, "ingestion.max_device_values", 1000))

    role_scores: dict[str, list[dict[str, Any]]] = {}
    for index, column in enumerate(columns):
        original = originals[index] if index < len(originals) else column
        role_scores[str(column)] = score_header_roles(original, vocab, config)

    # Long layout: a column explicitly recognised as a device identifier.
    device_candidates: list[tuple[float, str]] = []
    for index, column in enumerate(columns):
        original = originals[index] if index < len(originals) else column
        candidates = role_scores[str(column)]
        device_score = next((item["score"] for item in candidates if item["role"] == "device_id"), 0.0)
        if device_score >= minimum:
            series = frame[column]
            unique = series.dropna().nunique()
            if 0 < unique <= max_devices:
                device_candidates.append((device_score, str(column)))
    device_candidates.sort(key=lambda item: -item[0])

    # Structural fallback for an unfamiliar device column.
    if not device_candidates:
        unit_values: set[str] = set()
        for family in vocab.get("units", {}).values():
            canonical = family.get("canonical")
            if canonical:
                unit_values.add(normalize_text(canonical))
                unit_values.add(compact_text(canonical))
            for values in family.get("aliases", {}).values():
                for alias in values:
                    unit_values.add(normalize_text(alias))
                    unit_values.add(compact_text(alias))
        structural: list[tuple[float, str]] = []
        for column in columns:
            series = frame[column]
            non_null = series.dropna()
            if non_null.empty:
                continue
            unique = non_null.nunique()
            ratio = unique / max(len(non_null), 1)
            if 2 <= unique <= max_devices and ratio <= 0.5 and not pd.api.types.is_numeric_dtype(series):
                top_role = next((item["role"] for item in role_scores[str(column)] if item["score"] >= minimum), None)
                if top_role in {"availability_status", "event_description", "event_start", "event_end", "timestamp"}:
                    continue
                text_values = non_null.astype(str).str.strip()
                unit_like = text_values.map(
                    lambda value: normalize_text(value) in unit_values or compact_text(value) in unit_values
                )
                if float(unit_like.mean()) >= 0.80:
                    continue
                identifier_like = text_values.map(lambda value: len(value) >= 2)
                if float(identifier_like.mean()) < 0.50:
                    continue
                structural.append((0.55 + 0.2 * (1.0 - ratio), str(column)))
        structural.sort(key=lambda item: -item[0])
        if len(structural) == 1:
            device_candidates = structural
        elif len(structural) > 1:
            # Multiple plausible device columns: do not pick silently.
            device_candidates = []

    device_column = device_candidates[0][1] if len(device_candidates) == 1 else None
    devices: list[str] = []
    warnings: list[str] = []
    if len(device_candidates) > 1:
        warnings.append("Multiple columns could be device identifiers; long-layout device choice is unresolved.")
    if device_column is not None:
        devices = [str(value) for value in pd.unique(frame[device_column].dropna())]

    # Wide layout: device labels embedded in measurement column headers.
    column_devices: dict[str, str | None] = {str(column): None for column in columns}
    labeled_columns: list[str] = []
    labeled_devices: set[str] = set()
    for index, column in enumerate(columns):
        original = originals[index] if index < len(originals) else column
        top_role = next(
            (item["role"] for item in role_scores[str(column)] if item["score"] >= minimum),
            None,
        )
        if top_role not in DEVICE_LABELLED_ROLES:
            continue
        label = _extract_device_label(original, vocab)
        if label:
            column_devices[str(column)] = label
            if top_role in MEASUREMENT_ROLES:
                labeled_columns.append(str(column))
                labeled_devices.add(label)

    # Only device-labelled measurements establish a wide layout; labelled status
    # columns just follow their device.
    wide_detected = bool(labeled_columns) and (
        len(labeled_devices) >= 2 or len(labeled_columns) >= 2
    )

    if device_column is not None and wide_detected:
        layout_type = "ambiguous"
        warnings.append("Both a device column and device labels in headers were detected; long layout was preferred for device values.")
    elif device_column is not None:
        layout_type = "long"
    elif wide_detected:
        layout_type = "wide"
    elif any(
        next((item["role"] for item in role_scores[str(column)] if item["score"] >= minimum), None) in MEASUREMENT_ROLES
        for column in columns
    ):
        layout_type = "single"
    else:
        layout_type = "unknown"

    if layout_type == "wide" or (layout_type == "ambiguous" and wide_detected):
        devices = sorted(labeled_devices) if labeled_devices else devices

    return {
        "layout_type": layout_type,
        "device_id_source": "device_column" if device_column is not None else ("column_names" if wide_detected else None),
        "device_column": device_column,
        "devices": devices,
        "column_devices": column_devices,
        "warnings": warnings,
        "unresolved": layout_type in {"unknown", "ambiguous"} or (layout_type == "long" and device_column is None),
        "role_header_scores": {
            str(column): [
                {"role": item["role"], "score": item["score"], "matched_alias": item["matched_alias"]}
                for item in role_scores[str(column)]
            ]
            for column in columns
        },
    }


def _table_attribute(table: Any, name: str, default: Any = None) -> Any:
    if isinstance(table, dict):
        return table.get(name, default)
    return getattr(table, name, default)


def _generic_ambiguity(header: Any, config: dict[str, Any]) -> list[str] | None:
    normalized = normalize_text(header)
    mapping = get_path(config, "mapping.generic_ambiguous_headers", {}) or {}
    for key, roles in mapping.items():
        if normalized == normalize_text(key):
            return list(roles)
    return None


def _capacity_reference(
    frame: pd.DataFrame,
    fields: list[dict[str, Any]],
) -> float | None:
    capacity_fields = [item for item in fields if item.get("canonical_role") == "capacity" and not item.get("unresolved")]
    if not capacity_fields:
        return None
    field = capacity_fields[0]
    values = apply_conversion(frame[field["_internal_column"]], field.get("conversion"))
    unique = values.dropna().unique()
    if len(unique) == 1:
        return float(unique[0])
    return None


# In a device/rating table, a power-family column is a nameplate rating.
DEVICE_CONTEXT_ROLES = {"power_ac": "capacity", "power_dc": "dc_capacity"}
TIME_SERIES_ROLES = MEASUREMENT_ROLES | {"timestamp", "availability_status"}


def _context_candidates(candidates: list[dict[str, Any]], context: str | None) -> list[dict[str, Any]]:
    if context != "devices":
        return candidates
    best: dict[str, dict[str, Any]] = {}
    for item in candidates:
        role = DEVICE_CONTEXT_ROLES.get(item["role"], item["role"])
        if role in TIME_SERIES_ROLES:
            continue
        if role not in best or item["score"] > best[role]["score"]:
            best[role] = {**item, "role": role}
    return sorted(best.values(), key=lambda item: (-item["score"], item["role"]))


def map_table(
    table: Any,
    config: dict[str, Any] | None = None,
    vocab: dict[str, Any] | None = None,
    context: str | None = None,
) -> "MappingResult":
    """Map every source column in an ingested table and build a manifest.

    ``context="devices"`` maps a rating table: power columns become AC/DC ratings
    and time-series roles are not candidates.
    """

    config = config or load_defaults()
    vocab = vocab or load_vocab()
    frame: pd.DataFrame = _table_attribute(table, "frame")
    original_columns = list(_table_attribute(table, "original_columns", list(frame.columns)))
    layout = _table_attribute(table, "layout", {}) or {}
    timestamp_info = _table_attribute(table, "timestamp", {}) or {}
    source_file = str(_table_attribute(table, "source_file", ""))
    sheet_name = _table_attribute(table, "sheet_name", None)

    high_confidence = float(get_path(config, "mapping.high_confidence", 0.78))
    minimum_score = float(get_path(config, "mapping.minimum_candidate_score", 0.52))
    margin = float(get_path(config, "mapping.ambiguity_margin", 0.10))
    column_devices = layout.get("column_devices", {}) or {}
    column_units = _table_attribute(table, "column_units", {}) or {}

    fields: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, internal in enumerate(frame.columns):
        internal = str(internal)
        if internal.startswith("__"):
            continue
        original = str(original_columns[index]) if index < len(original_columns) else internal
        series = frame[internal]
        # Unit evidence: the header plus any units row captured during ingestion.
        unit_text = f"{original} [{column_units[internal]}]" if column_units.get(internal) else original
        candidates = _context_candidates(score_header_roles(original, vocab, config), context)
        generic_roles = _generic_ambiguity(original, config)
        warnings_for_field: list[str] = []
        unresolved_reasons: list[str] = []

        # Explicit ingestion timestamp detection wins over header scoring.
        timestamp_columns = set(timestamp_info.get("columns", []) or [])
        if original in timestamp_columns or internal in timestamp_columns:
            role = "timestamp"
            unit = None
            conversion = None
            confidence = 1.0
            validation_status = "pass"
            validation = {"status": "pass", "checks": []}
            matched_alias = "ingestion timestamp detector"
        else:
            if generic_roles:
                candidate_roles = generic_roles
                unresolved_reasons.append(
                    "Header is generic and does not distinguish between: " + ", ".join(generic_roles)
                )
                # Keep candidate scores for the manifest, but force unresolved.
                scored = {item["role"]: item for item in candidates}
                confidence = max((scored.get(role, {}).get("score", 0.0) for role in candidate_roles), default=0.0)
                role = None
                unit = None
                conversion = None
                validation_status = "unresolved"
                validation = {"status": "unresolved", "checks": []}
                matched_alias = None
            else:
                usable = [item for item in candidates if item["score"] >= minimum_score]
                if not usable:
                    role = None
                    unit = None
                    conversion = None
                    confidence = 0.0
                    validation_status = "unresolved"
                    validation = {"status": "unresolved", "checks": []}
                    matched_alias = None
                    unresolved_reasons.append("No vocabulary match above the minimum score.")
                else:
                    scored_candidates: list[dict[str, Any]] = []
                    for item in usable:
                        candidate_unit, _ = infer_header_unit(unit_text, item["role"], vocab)
                        value_adjustment, value_warnings = _value_evidence(series, item["role"], config)
                        score = item["score"] + (0.06 if candidate_unit else 0.0) + value_adjustment
                        scored_candidates.append(
                            {
                                **item,
                                "unit": candidate_unit,
                                "score": round(min(max(score, 0.0), 1.0), 4),
                                "value_warnings": value_warnings,
                            }
                        )
                    scored_candidates.sort(key=lambda item: (-item["score"], item["role"]))
                    top = scored_candidates[0]
                    role = top["role"]
                    unit = top["unit"]
                    role, unit, reconcile_note = _reconcile_role_with_unit(role, unit, unit_text, vocab)
                    if reconcile_note:
                        warnings_for_field.append(reconcile_note)
                    conversion = _conversion_for(role, unit, vocab)
                    confidence = top["score"]
                    matched_alias = top["matched_alias"]
                    warnings_for_field.extend(top.get("value_warnings", []))

                    competitor = next(
                        (
                            item
                            for item in scored_candidates[1:]
                            if item["role"] != role and item["score"] >= top["score"] - margin
                        ),
                        None,
                    )
                    if competitor is not None:
                        unresolved_reasons.append(
                            f"Ambiguous between {role} ({top['score']:.2f}) and "
                            f"{competitor['role']} ({competitor['score']:.2f})."
                        )
                        role = None
                        confidence = top["score"]
                        validation_status = "unresolved"
                        validation = {"status": "unresolved", "checks": []}
                    elif confidence < high_confidence:
                        unresolved_reasons.append(
                            f"Confidence {confidence:.2f} is below the acceptance threshold {high_confidence:.2f}."
                        )
                        role = None
                        validation_status = "unresolved"
                        validation = {"status": "unresolved", "checks": []}
                    else:
                        validation_status, validation, validation_warnings = _field_validation(
                            role, series, unit, conversion, config
                        )
                        warnings_for_field.extend(validation_warnings)
                        if _role_unit_required(role, config) and unit is None:
                            unresolved_reasons.append("Unit could not be established from the header or units row.")
                        if validation_status == "fail" and role is not None:
                            unresolved_reasons.append("Field failed mapping validation.")
                            role = None

                    if role is None and not unresolved_reasons:
                        unresolved_reasons.append("Mapping did not pass deterministic acceptance checks.")

        device_id = column_devices.get(internal)
        field_manifest = {
            "source_file": source_file,
            "sheet_name": sheet_name,
            "source_column": original,
            "source_column_index": index,
            "internal_column": internal,
            "_internal_column": internal,
            "canonical_role": role,
            "device_id": device_id,
            "detected_unit": unit,
            "canonical_unit": _canonical_unit(role, vocab),
            "conversion": conversion,
            "confidence": round(float(confidence), 4),
            "matched_alias": matched_alias,
            "validation_result": validation,
            "warnings": warnings_for_field,
            "unresolved": role is None,
            "unresolved_reasons": unresolved_reasons,
            "mapping_version": MAPPING_VERSION,
            "provenance": {
                "method": "deterministic_vocabulary_and_value_checks",
                "vocab_version": vocab.get("vocab_version"),
                "source": "configs/schema_vocab.yaml",
            },
        }
        fields.append(field_manifest)

    # Resolve duplicate role/device candidates without silently dropping fields.
    accepted_by_key: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for item in fields:
        if item["canonical_role"] in DEDUPE_ROLES and not item["unresolved"]:
            key = (item["canonical_role"], item["device_id"])
            accepted_by_key.setdefault(key, []).append(item)
    for (role_name, device_id), items in accepted_by_key.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda item: (-item["confidence"], item["source_column_index"]))
        for duplicate in items[1:]:
            duplicate["unresolved"] = True
            duplicate["canonical_role"] = None
            duplicate["unresolved_reasons"].append(
                f"Duplicate candidate for role {role_name} and device {device_id!r}; higher-confidence field retained."
            )
            duplicate["validation_result"] = {"status": "unresolved", "checks": []}

    capacity_kw = _capacity_reference(frame, fields)
    if capacity_kw is not None:
        for item in fields:
            if item.get("canonical_role") in {"power_ac", "power_dc"} and not item["unresolved"]:
                status, validation, extra_warnings = _field_validation(
                    item["canonical_role"],
                    frame[item["_internal_column"]],
                    item.get("detected_unit"),
                    item.get("conversion"),
                    config,
                    capacity_kw=capacity_kw,
                )
                item["validation_result"] = validation
                item["warnings"].extend(extra_warnings)
                if status == "fail":
                    item["unresolved"] = True
                    item["unresolved_reasons"].append("Power exceeds the documented capacity tolerance.")
                    item["canonical_role"] = None

    role_to_columns: dict[str, list[str]] = {}
    for item in fields:
        if item["canonical_role"] and not item["unresolved"]:
            role_to_columns.setdefault(item["canonical_role"], []).append(item["internal_column"])

    for item in fields:
        item.pop("_internal_column", None)

    unresolved_fields = [item["source_column"] for item in fields if item["unresolved"]]
    manifest = {
        "mapping_version": MAPPING_VERSION,
        "source_file": source_file,
        "sheet_name": sheet_name,
        "row_count": int(len(frame)),
        "column_count": int(sum(1 for column in frame.columns if not str(column).startswith("__"))),
        "layout": json_safe(layout),
        "timestamp": json_safe(timestamp_info),
        "fields": json_safe(fields),
        "role_to_columns": {role: list(columns) for role, columns in role_to_columns.items()},
        "unresolved_fields": unresolved_fields,
        "warnings": warnings,
        "provenance": {
            "method": "deterministic_vocabulary_and_value_checks",
            "vocab_version": vocab.get("vocab_version"),
            "vocab_file": "configs/schema_vocab.yaml",
            "mapping_version": MAPPING_VERSION,
        },
    }
    return MappingResult(
        manifest=manifest,
        fields=fields,
        role_to_columns=role_to_columns,
        unresolved_fields=unresolved_fields,
    )


def _canonical_unit(role: str | None, vocab: dict[str, Any]) -> str | None:
    family = UNIT_FAMILY_ROLES.get(role or "")
    if family is None:
        return None
    return vocab.get("units", {}).get(family, {}).get("canonical")


@dataclass
class MappingResult:
    """Result of deterministic schema mapping."""

    manifest: dict[str, Any]
    fields: list[dict[str, Any]] = field(default_factory=list)
    role_to_columns: dict[str, list[str]] = field(default_factory=dict)
    unresolved_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.manifest

    def to_manifest(self) -> dict[str, Any]:
        return self.manifest


def map_columns(columns: Iterable[str], config: dict[str, Any] | None = None, vocab: dict[str, Any] | None = None) -> dict[str, str | None]:
    """Compatibility helper: map bare column names without value evidence."""

    config = config or load_defaults()
    vocab = vocab or load_vocab()
    result: dict[str, str | None] = {}
    for column in columns:
        candidates = score_header_roles(column, vocab, config)
        result[str(column)] = candidates[0]["role"] if candidates else None
    return result
