#!/usr/bin/env python3
"""Inspect and standardize solar-plant CSV/XLSX data using explicit column mappings.

Column names are never assumed to be universal. The CLI first suggests mappings;
a mapping file is required before producing standardized records.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

CANONICAL_FIELDS = {
    "timestamp": "Date/time of the measurement",
    "plant_id": "Plant/site identifier",
    "device_id": "Inverter/device identifier",
    "actual_power": "Measured instantaneous power",
    "expected_power": "Reference/expected instantaneous power",
    "energy": "Energy generated over a stated interval",
    "irradiance": "Solar irradiance",
    "inverter_status": "Device operational/status signal",
    "ambient_temperature": "Ambient air temperature",
    "module_temperature": "PV module temperature",
    "voltage": "Electrical voltage",
    "current": "Electrical current",
    "event_code": "Event/alarm code",
}

# These are suggestions only. They do not establish units, meaning, or validity.
ALIASES = {
    "timestamp": ["timestamp", "datetime", "date time", "date", "time", "recorded at", "measurement time"],
    "plant_id": ["plant id", "site id", "plant", "site", "station id"],
    "device_id": ["device id", "inverter id", "inverter", "asset id", "equipment id"],
    "actual_power": ["actual power", "measured power", "active power", "output power", "power output", "pac", "ac power", "power kw"],
    "expected_power": ["expected power", "theoretical power", "predicted power", "target power", "reference power"],
    "energy": ["energy", "energy generated", "yield", "daily energy", "energy kwh", "production kwh"],
    "irradiance": ["irradiance", "poa", "ghi", "plane of array", "solar radiation"],
    "inverter_status": ["inverter status", "device status", "status", "operating state", "state"],
    "ambient_temperature": ["ambient temperature", "air temperature", "ambient temp", "air temp"],
    "module_temperature": ["module temperature", "panel temperature", "cell temperature", "module temp"],
    "voltage": ["voltage", "dc voltage", "ac voltage"],
    "current": ["current", "dc current", "ac current"],
    "event_code": ["event code", "alarm code", "fault code", "event", "alarm", "fault"],
}


def normalize_name(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[_./\\-]+", " ", text)
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", text)).strip()


def read_table(path: Path, sheet: str | int | None = None) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        sheet_name: str | int = 0 if sheet is None else (int(sheet) if str(sheet).isdigit() else str(sheet))
        return pd.read_excel(path, sheet_name=sheet_name)
    raise ValueError("Unsupported file type. Supply CSV, XLSX, or XLS.")


def suggest_mappings(columns: list[str]) -> dict[str, dict[str, Any]]:
    """Return suggestions, not confirmed mappings. Ties are reported as ambiguous."""
    normalized = {column: normalize_name(column) for column in columns}
    suggestions: dict[str, dict[str, Any]] = {}
    for field, aliases in ALIASES.items():
        alias_norms = {normalize_name(alias) for alias in aliases}
        scored = []
        for column, name in normalized.items():
            score = 0
            if name in alias_norms:
                score = 100
            else:
                for alias in alias_norms:
                    if alias and (alias in name or name in alias):
                        score = max(score, 65 if len(alias) > 3 and len(name) > 3 else 0)
            if score:
                scored.append((score, column))
        scored.sort(reverse=True)
        if not scored:
            suggestions[field] = {"description": CANONICAL_FIELDS[field], "status": "not_found", "candidates": []}
        else:
            best_score = scored[0][0]
            best = [column for score, column in scored if score == best_score]
            suggestions[field] = {
                "description": CANONICAL_FIELDS[field],
                "status": "suggested" if len(best) == 1 else "ambiguous",
                "candidates": best,
                "score": best_score,
            }
    return suggestions


def load_mapping(path: Path, columns: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
    config = json.loads(path.read_text(encoding="utf-8"))
    raw_mapping = config.get("columns", config)
    if not isinstance(raw_mapping, dict):
        raise ValueError("Mapping JSON must be an object or contain an object under 'columns'.")
    mapping: dict[str, str] = {}
    units: dict[str, str] = config.get("units", {}) if isinstance(config.get("units", {}), dict) else {}
    valid_fields = set(CANONICAL_FIELDS)
    for field, column in raw_mapping.items():
        if field in {"units", "notes"}:
            continue
        if field not in valid_fields:
            raise ValueError(f"Unknown canonical field {field!r}. Allowed fields: {', '.join(sorted(valid_fields))}")
        if column is None or column == "":
            continue
        if not isinstance(column, str) or column not in columns:
            raise ValueError(f"Mapped source column for {field!r} must exactly match an input column: {column!r}")
        if column in mapping.values():
            raise ValueError(f"Source column {column!r} is mapped more than once. Confirm intent and use a separate mapping strategy if needed.")
        mapping[field] = column
    if "timestamp" not in mapping:
        raise ValueError("A confirmed 'timestamp' mapping is required to standardize time-series data.")
    return mapping, {str(k): str(v) for k, v in units.items()}


def json_safe(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def standardize(df: pd.DataFrame, mapping: dict[str, str], units: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output = []
    warnings: list[str] = []
    timestamp_source = mapping["timestamp"]
    parsed_timestamps = pd.to_datetime(df[timestamp_source], errors="coerce", utc=False)
    invalid_count = int(parsed_timestamps.isna().sum())
    if invalid_count:
        warnings.append(f"{invalid_count} row(s) have missing or unparseable timestamps; retained with null timestamp.")
    for row_index, (_, row) in enumerate(df.iterrows()):
        record: dict[str, Any] = {
            "source_row_number": row_index + 2,
            "source_columns": {str(col): json_safe(row[col]) for col in df.columns},
            "values": {},
            "units": {},
            "mapping": {},
        }
        for field, source_col in mapping.items():
            value = parsed_timestamps.iloc[row_index] if field == "timestamp" else row[source_col]
            record["values"][field] = json_safe(value)
            record["mapping"][field] = source_col
            if field in units:
                record["units"][field] = units[field]
        output.append(record)

    duplicate_count = int(parsed_timestamps.dropna().duplicated().sum())
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate timestamp row(s) detected; no rows were dropped.")
    metadata = {
        "input_rows": int(len(df)),
        "input_columns": [str(c) for c in df.columns],
        "mapped_fields": list(mapping.keys()),
        "unmapped_columns": [str(c) for c in df.columns if c not in mapping.values()],
        "units_are_user_supplied": True,
        "warnings": warnings,
        "limitations": [
            "Column suggestions are heuristic and require human confirmation.",
            "No unit conversion, missing-value imputation, anomaly detection, or root-cause diagnosis is performed.",
            "Timestamp timezone is not inferred; confirm timezone and daylight-saving assumptions separately.",
            "Expected power, energy, and instantaneous power are distinct quantities and must not be interchanged.",
        ],
    }
    return output, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input CSV/XLSX/XLS file")
    parser.add_argument("--sheet", help="Excel sheet name or zero-based index (default: first sheet)")
    parser.add_argument("--mapping", type=Path, help="JSON file with explicitly confirmed column mappings")
    parser.add_argument("--output", type=Path, help="Output JSONL path; required with --mapping")
    parser.add_argument("--report", type=Path, help="Optional path for the inspection/mapping report JSON")
    args = parser.parse_args()

    try:
        df = read_table(args.input, args.sheet)
        columns = [str(c) for c in df.columns]
        report = {
            "input_file": str(args.input),
            "row_count": int(len(df)),
            "columns": columns,
            "sample_rows": [{str(k): json_safe(v) for k, v in row.items()} for row in df.head(5).to_dict(orient="records")],
            "mapping_suggestions": suggest_mappings(columns),
            "canonical_fields": CANONICAL_FIELDS,
        }
        if args.mapping:
            if not args.output:
                raise ValueError("--output is required when --mapping is provided.")
            mapping, units = load_mapping(args.mapping, columns)
            records, metadata = standardize(df, mapping, units)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            report["standardization"] = metadata
            report["confirmed_mapping"] = mapping
            print(f"Standardized {len(records)} rows -> {args.output}")
            print(f"Mapped fields: {', '.join(mapping.keys())}")
            for warning in metadata["warnings"]:
                print(f"WARNING: {warning}")
        else:
            print("Inspection only; no source columns were mapped automatically.")
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            print(f"Report saved -> {args.report}")
        return 0
    except (FileNotFoundError, ValueError, json.JSONDecodeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
