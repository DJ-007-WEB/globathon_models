"""Adaptive CSV/Excel ingestion with structure and timestamp discovery.

This module reads files without assuming plant capacity, device count, column
names, units, timestamp format, time zone or sampling interval.  It preserves
source column names, leaves missing readings as NaN, and records every
unresolved ambiguity in a JSON-safe manifest.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from .config import get_path, json_safe, load_defaults, load_vocab
from .schema_mapping import detect_layout, normalize_text, score_header_roles

UTC_COLUMN = "__timestamp_utc__"
LOCAL_COLUMN = "__timestamp_local__"
RAW_TIMESTAMP_COLUMN = "__timestamp_raw__"
ROW_ORDER_COLUMN = "__row_order__"

_DATE_YMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_DATE_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$")
_TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(\s*[AaPp][Mm])?$")
_OFFSET_AT_END = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
_IANA = re.compile(r"\b((?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b")
_AMBIGUOUS_ABBREVIATIONS = {
    "ist",
    "bst",
    "cst",
    "cdt",
    "est",
    "edt",
    "mst",
    "mdt",
    "pst",
    "pdt",
    "cet",
    "cest",
    "eet",
    "eest",
    "aest",
    "aedt",
}


@dataclass
class TableData:
    """One CSV file or one Excel sheet, plus its discovery metadata."""

    source_file: str
    sheet_name: str | None
    frame: pd.DataFrame
    original_columns: list[str]
    raw_headers: list[str]
    column_aliases: dict[str, str]
    header: dict[str, Any]
    layout: dict[str, Any]
    timestamp: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    dropped_empty_rows: int = 0
    dropped_empty_columns: int = 0
    dropped_empty_column_names: list[str] = field(default_factory=list)
    encoding: str | None = None
    delimiter: str | None = None
    column_units: dict[str, str] = field(default_factory=dict)
    unit_rows_skipped: int = 0

    def to_manifest(self) -> dict[str, Any]:
        profiles = []
        for column in self.frame.columns:
            if str(column).startswith("__"):
                continue
            series = self.frame[column]
            non_null = int(series.notna().sum())
            samples = [value for value in series.dropna().head(5).tolist()]
            profiles.append(
                {
                    "source_column": self.column_aliases.get(str(column), str(column)),
                    "internal_column": str(column),
                    "dtype": str(series.dtype),
                    "non_null": non_null,
                    "missing": int(len(series) - non_null),
                    "missing_fraction": round(float(1.0 - non_null / max(len(series), 1)), 4),
                    "unique": int(series.nunique(dropna=True)),
                    "sample_values": json_safe(samples),
                }
            )
        return {
            "source_file": self.source_file,
            "sheet_name": self.sheet_name,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "row_count": int(len(self.frame)),
            "column_count": int(len(profiles)),
            "header": json_safe(self.header),
            "layout": json_safe(self.layout),
            "timestamp": json_safe(self.timestamp),
            "columns": profiles,
            "warnings": list(self.warnings),
            "dropped_empty_rows": self.dropped_empty_rows,
            "dropped_empty_columns": self.dropped_empty_columns,
            "dropped_empty_column_names": list(self.dropped_empty_column_names),
            "column_units": {self.column_aliases.get(key, key): value for key, value in self.column_units.items()},
            "unit_rows_skipped": self.unit_rows_skipped,
            "derived_columns": [UTC_COLUMN, LOCAL_COLUMN, RAW_TIMESTAMP_COLUMN, ROW_ORDER_COLUMN],
        }


@dataclass
class IngestionResult:
    """Result of ingesting one file, which may contain several sheets."""

    source_file: str
    file_type: str
    tables: list[TableData] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.tables)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "file_type": self.file_type,
            "ok": self.ok,
            "table_count": len(self.tables),
            "tables": [table.to_manifest() for table in self.tables],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _is_empty(value: Any) -> bool:
    if value is None or value is pd.NaT or value is pd.NA:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _numeric_like(value: Any) -> bool:
    if _is_empty(value):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return True
    text = str(value).strip()
    if not text:
        return False
    if re.match(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$", text):
        return True
    if re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", text):
        return True
    return False


_UNIT_TOKEN = re.compile(
    r"^[\[(]?\s*(?:"
    r"[kmgµu]?(?:w|wh|va|var|vah|varh|wp)(?:\s*/\s*(?:m2|m²|m\^2|sqm|kwp))?"
    r"|°\s*[cfk]?|deg\s*[cf]?|degrees?\s*[cf]?|[cf]|%|pct|percent|m/s|km/h|mph|mm|hpa|kpa|pa|bar"
    r"|[kmu]?v|[km]?a|hz|s|sec|secs|min|mins|h|hr|hrs|ratio|-|pu|p\.u\.|n/a|na|unit|units|kwh/kwp"
    r")\s*[\])]?$",
    re.IGNORECASE,
)
_DATE_FORMAT_TOKEN = re.compile(r"^(?:(?:yyyy|yy|mm|dd|hh|ss|m|d|h)[-/.: t]?)+$", re.IGNORECASE)


def _unit_like(value: Any) -> bool:
    """True for cells such as 'kW', '[W/m²]', '°C' or 'dd-mm-yyyy hh:mm' in a units row."""
    if _is_empty(value) or _numeric_like(value):
        return False
    text = str(value).strip()
    return bool(_UNIT_TOKEN.match(text) or _DATE_FORMAT_TOKEN.match(text))


def _is_unit_row(values: list[Any]) -> bool:
    """A row is a units/metadata row when most non-empty cells are units and none are numeric."""
    non_empty = [value for value in values if not _is_empty(value)]
    if not non_empty or any(_numeric_like(value) for value in non_empty):
        return False
    return sum(1 for value in non_empty if _unit_like(value)) / len(non_empty) >= 0.6


def _date_like_ratio(series: pd.Series) -> float:
    values = [str(value).strip() for value in series.dropna().head(200)]
    if not values:
        return 0.0
    hits = 0
    for text in values:
        date_part = re.split(r"[ T]", text, maxsplit=1)[0]
        if _DATE_YMD.match(date_part) or _DATE_DMY.match(date_part):
            hits += 1
    return hits / len(values)


def _time_like_ratio(series: pd.Series) -> float:
    values = [str(value).strip() for value in series.dropna().head(200)]
    if not values:
        return 0.0
    return sum(1 for value in values if _TIME_ONLY.match(value)) / len(values)


def detect_header_row(
    raw: pd.DataFrame,
    vocab: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Detect the most likely header row in a raw (header=None) grid."""

    if raw.empty or len(raw.columns) == 0:
        return {
            "header_row": 0,
            "confidence": 0.0,
            "ambiguous": True,
            "candidates": [],
            "warnings": ["No rows available for header detection."],
        }

    max_scan = min(int(get_path(config, "ingestion.max_header_scan_rows", 30)), len(raw))
    ncols = max(len(raw.columns), 1)
    candidates: list[dict[str, Any]] = []
    for index in range(max_scan):
        row = raw.iloc[index]
        values = [value for value in row.tolist() if not _is_empty(value)]
        if not values:
            continue
        header_ratio = len(values) / ncols
        unique_ratio = len({str(value).strip().lower() for value in values}) / max(len(values), 1)
        text_ratio = sum(1 for value in values if not _numeric_like(value)) / len(values)
        vocab_hits = 0
        for value in values:
            scores = score_header_roles(value, vocab, config)
            if scores and scores[0]["score"] >= 0.60:
                vocab_hits += 1
        vocab_score = min(vocab_hits / max(min(len(values), 5), 1), 1.0)

        next_rows = raw.iloc[index + 1 : index + 6]
        if len(next_rows):
            data_cells = [value for value in next_rows.to_numpy().ravel().tolist()]
            data_non_empty = sum(1 for value in data_cells if not _is_empty(value)) / max(len(data_cells), 1)
            data_numeric = sum(1 for value in data_cells if _numeric_like(value) or _date_like_ratio(pd.Series([value])) > 0) / max(len(data_cells), 1)
        else:
            data_non_empty = 0.0
            data_numeric = 0.0

        score = (
            0.34 * header_ratio
            + 0.14 * unique_ratio
            + 0.16 * text_ratio
            + 0.16 * data_non_empty
            + 0.12 * data_numeric
            + 0.22 * vocab_score
        )
        if header_ratio < 0.5:
            score *= 0.55
        # Unit tokens often score well against aliases ("W/m2", "kW"); a units row
        # directly under the real header must not win header detection.
        unit_row = _is_unit_row(row.tolist())
        if unit_row:
            score *= 0.35
        candidates.append(
            {
                "header_row": index,
                "score": round(score, 4),
                "header_ratio": round(header_ratio, 4),
                "text_ratio": round(text_ratio, 4),
                "vocab_hits": vocab_hits,
                "data_numeric_ratio": round(data_numeric, 4),
                "unit_row": unit_row,
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["header_row"]))
    if not candidates:
        return {
            "header_row": 0,
            "confidence": 0.0,
            "ambiguous": True,
            "candidates": [],
            "warnings": ["No non-empty candidate header row was found."],
        }

    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    margin = best["score"] - (second["score"] if second else 0.0)
    minimum = float(get_path(config, "ingestion.header_confidence_min", 0.55))
    required_margin = float(get_path(config, "ingestion.header_margin_min", 0.08))
    ambiguous = best["score"] < minimum or margin < required_margin
    warnings: list[str] = []
    if ambiguous:
        warnings.append(
            f"Header row detection is uncertain (score={best['score']:.2f}, margin={margin:.2f}); "
            f"row {best['header_row']} was used for structure reporting."
        )

    return {
        "header_row": int(best["header_row"]),
        "confidence": round(float(best["score"]), 4),
        "margin": round(float(margin), 4),
        "ambiguous": bool(ambiguous),
        "candidates": candidates[:5],
        "warnings": warnings,
    }


def _read_csv_raw(
    path: Path,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, str, str]:
    encodings = list(get_path(config, "ingestion.csv_encodings", ["utf-8-sig", "utf-8", "cp1252", "latin-1"]))
    text: str | None = None
    encoding_used: str | None = None
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if text is None:
        raise ValueError(f"Unable to decode CSV with configured encodings: {last_error}")

    delimiters = list(get_path(config, "ingestion.csv_delimiters", [",", ";", "\t", "|"]))
    sample = text[:8192]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(delimiters))
        delimiter = dialect.delimiter
    except csv.Error:
        counts = {candidate: sample.count(candidate) for candidate in delimiters}
        delimiter = max(counts, key=counts.get) if counts else ","

    from io import StringIO

    # Read with the standard-library CSV reader so preamble rows with fewer
    # fields than the data table do not cause pandas to infer a one-column file.
    rows = list(csv.reader(StringIO(text), delimiter=delimiter))
    max_fields = max((len(row) for row in rows), default=0)
    padded = [row + [""] * (max_fields - len(row)) for row in rows]
    raw = pd.DataFrame(padded, dtype=object)
    return raw, str(encoding_used), str(delimiter)


def _read_excel_raw(path: Path) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(path, engine="openpyxl")
    return {
        str(sheet): pd.read_excel(workbook, sheet_name=sheet, header=None, dtype=object)
        for sheet in workbook.sheet_names
    }


def _unique_headers(header_values: Iterable[Any]) -> tuple[list[str], list[str], dict[str, str]]:
    raw_headers: list[str] = []
    display: list[str] = []
    internal: list[str] = []
    aliases: dict[str, str] = {}
    counts: dict[str, int] = {}
    for index, value in enumerate(header_values):
        text = "" if _is_empty(value) else str(value).strip()
        raw_headers.append(text)
        label = text if text else f"<unnamed column {index}>"
        display.append(label)
        base = text if text else f"Unnamed_{index}"
        counts[base] = counts.get(base, 0) + 1
        name = base if counts[base] == 1 else f"{base}__{counts[base]}"
        while name in aliases:
            counts[base] += 1
            name = f"{base}__{counts[base]}"
        internal.append(name)
        aliases[name] = label
    return raw_headers, display, aliases


def _infer_series(series: pd.Series, warnings: list[str], label: str) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    cleaned = series.map(lambda value: value.strip() if isinstance(value, str) else value)
    cleaned = cleaned.map(lambda value: np.nan if isinstance(value, str) and not value else value)
    non_null = cleaned.dropna()
    if non_null.empty:
        return cleaned

    values = [str(value).strip() for value in non_null]
    leading_zero_ids = sum(1 for value in values if re.match(r"^0\d+$", value))
    if leading_zero_ids > 1 and leading_zero_ids / len(values) > 0.5:
        warnings.append(f"Column {label!r} contains leading-zero identifiers; kept as text.")
        return cleaned.astype(object)

    numeric_mask = cleaned.map(_numeric_like)
    ratio = float(numeric_mask.sum() / max(len(non_null), 1))
    if ratio >= 0.95:
        converted_text = cleaned.map(
            lambda value: value.replace(",", "") if isinstance(value, str) and re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", value) else value
        )
        numeric = pd.to_numeric(converted_text, errors="coerce")
        if numeric.notna().sum() >= max(int(0.95 * len(non_null)), 1):
            return numeric
    if ratio >= 0.5 and ratio < 0.95:
        warnings.append(f"Column {label!r} is partially numeric ({ratio:.0%}); left unconverted to avoid guessing.")
    return cleaned.astype(object)


def _strip_time(text: str) -> str:
    return re.split(r"[ T]", str(text).strip(), maxsplit=1)[0]


def _detect_date_order(values: Iterable[Any], header_text: str = "", override: str | None = None) -> dict[str, Any]:
    texts = [str(value).strip() for value in values if not _is_empty(value)]
    if not texts:
        return {"order": None, "reason": "No date values available.", "evidence": []}
    if override:
        order = str(override).strip().upper()
        if order not in {"DMY", "MDY", "YMD"}:
            return {"order": None, "reason": f"Unsupported date-order override {override!r}.", "evidence": []}
        return {"order": order, "reason": "Date order supplied explicitly by the caller.", "evidence": ["override"]}

    ymd = 0
    other = 0
    first_values: list[int] = []
    second_values: list[int] = []
    two_digit_year = False
    separators: set[str] = set()
    # Scan every value: a month whose first rows are days 01-12 is only
    # disambiguated later in the column.
    for text in dict.fromkeys(texts):
        date_part = _strip_time(text)
        match = _DATE_YMD.match(date_part)
        if match:
            ymd += 1
            separators.add(date_part[4])
            continue
        match = _DATE_DMY.match(date_part)
        if match:
            other += 1
            first_values.append(int(match.group(1)))
            second_values.append(int(match.group(2)))
            if len(match.group(3)) == 2:
                two_digit_year = True
            for separator in "-/.":
                if separator in date_part:
                    separators.add(separator)
                    break

    if ymd and other:
        return {"order": None, "reason": "Mixed year-first and day/month-first date formats.", "evidence": ["mixed formats"]}
    if ymd:
        if len(separators) > 1:
            return {"order": None, "reason": "Mixed date separators.", "evidence": sorted(separators)}
        return {"order": "YMD", "reason": "Year-first date format.", "evidence": ["year first"]}
    if not other:
        return {"order": None, "reason": "Values do not match a supported date pattern.", "evidence": []}
    if len(separators) > 1:
        return {"order": None, "reason": "Mixed date separators.", "evidence": sorted(separators)}
    if two_digit_year:
        return {
            "order": None,
            "reason": "Two-digit years are ambiguous; century cannot be established.",
            "evidence": ["two-digit year"],
        }

    normalized_header = normalize_text(header_text)
    header_evidence: str | None = None
    if re.search(r"\b(dd[/ -]?mm|day first|dmy)\b", normalized_header):
        header_evidence = "DMY"
    elif re.search(r"\b(mm[/ -]?dd|month first|mdy)\b", normalized_header):
        header_evidence = "MDY"

    first_over = any(value > 12 for value in first_values)
    second_over = any(value > 12 for value in second_values)
    if first_over and second_over:
        return {"order": None, "reason": "Day and month fields both exceed 12; date order is contradictory.", "evidence": ["both > 12"]}
    if first_over and second_over is False:
        order = "DMY"
        evidence = "day value exceeds 12"
    elif second_over and first_over is False:
        order = "MDY"
        evidence = "month-position value exceeds 12"
    elif header_evidence:
        order = header_evidence
        evidence = "header text"
    else:
        return {
            "order": None,
            "reason": "All day/month values are <= 12 and no header evidence establishes order; day/month order is unresolved.",
            "evidence": ["all day/month values <= 12"],
        }
    if header_evidence and header_evidence != order:
        return {
            "order": None,
            "reason": "Header date-order hint conflicts with value evidence.",
            "evidence": [evidence, "header text"],
        }
    return {"order": order, "reason": f"Date order established from {evidence}.", "evidence": [evidence]}


def _strip_timezone_suffix(text: str) -> str:
    return _OFFSET_AT_END.sub("", str(text).strip())


def _detect_time_format(values: Iterable[Any]) -> dict[str, Any]:
    texts = [_strip_timezone_suffix(value) for value in values if not _is_empty(value)]
    if not texts:
        return {"format": None, "text": None, "reason": "No time values available."}
    formats = {
        r"^\d{1,2}:\d{2}:\d{2}\.\d+$": ("%H:%M:%S.%f", "HH:MM:SS.ffffff"),
        r"^\d{1,2}:\d{2}:\d{2}\s*[AaPp][Mm]$": ("%I:%M:%S %p", "hh:mm:ss AM/PM"),
        r"^\d{1,2}:\d{2}\s*[AaPp][Mm]$": ("%I:%M %p", "hh:mm AM/PM"),
        r"^\d{1,2}:\d{2}:\d{2}$": ("%H:%M:%S", "HH:MM:SS"),
        r"^\d{1,2}:\d{2}$": ("%H:%M", "HH:MM"),
    }
    matched: list[str] = []
    for text in texts[:500]:
        for pattern, (fmt, label) in formats.items():
            if re.match(pattern, text):
                matched.append(fmt)
                break
    if not matched:
        return {"format": None, "text": None, "reason": "Time values do not match a supported format."}
    unique = sorted(set(matched))
    if len(unique) > 1:
        # Prefer the most precise format if the only difference is seconds.
        if set(unique).issubset({"%H:%M", "%H:%M:%S"}):
            return {"format": "%H:%M:%S", "text": "HH:MM:SS", "reason": "Mixed minute/second precision."}
        return {"format": None, "text": None, "reason": "Mixed time formats."}
    fmt = unique[0]
    label = next(label for pattern, (candidate, label) in formats.items() if candidate == fmt)
    return {"format": fmt, "text": label, "reason": "Consistent time format."}


def _detect_value_timezone(values: Iterable[Any]) -> dict[str, Any]:
    offsets: set[str] = set()
    has_z = False
    texts = [str(value).strip() for value in values if not _is_empty(value)]
    for text in texts[:500]:
        match = _OFFSET_AT_END.search(text)
        if match:
            token = match.group(1)
            if token.upper() == "Z":
                has_z = True
            else:
                offsets.add(token)
    if not offsets and not has_z:
        return {"timezone": None, "source": None, "reason": "No explicit offset in timestamp values."}
    if has_z and not offsets:
        return {"timezone": "UTC", "source": "values", "reason": "Timestamp values end in Z."}
    if len(offsets) == 1 and not has_z:
        return {"timezone": next(iter(offsets)), "source": "values", "reason": "Timestamp values carry a consistent UTC offset."}
    return {
        "timezone": "mixed offsets",
        "source": "values",
        "reason": "Timestamp values carry multiple UTC offsets; normalized to UTC.",
    }


def _detect_header_timezone(header_text: str, config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_text(header_text)
    aliases = get_path(config, "time.unambiguous_timezone_aliases", {}) or {}
    for alias, canonical in aliases.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(normalize_text(alias)) + r"(?![a-z0-9])", normalized):
            return {"timezone": str(canonical), "source": "header", "reason": f"Header contains time-zone token {alias!r}."}
    iana = _IANA.search(header_text)
    if iana:
        return {"timezone": iana.group(1), "source": "header", "reason": "Header contains an IANA time-zone name."}
    offset = re.search(r"(?<!\d)([+-]\d{1,2}:?\d{2})(?!\d)", header_text)
    if offset:
        return {"timezone": offset.group(1), "source": "header", "reason": "Header contains a UTC offset."}
    for token in normalize_text(header_text).split():
        if token in _AMBIGUOUS_ABBREVIATIONS:
            return {
                "timezone": None,
                "source": "header",
                "reason": f"Time-zone abbreviation {token.upper()!r} is ambiguous and was not used.",
            }
    return {"timezone": None, "source": None, "reason": "No time zone in header."}


def _timezone_from_text(value: str) -> Any:
    if value == "UTC":
        return "UTC"
    if value.startswith(("+", "-")):
        sign = 1 if value[0] == "+" else -1
        body = value[1:].replace(":", "")
        if len(body) == 4 and body.isdigit():
            hours = int(body[:2])
            minutes = int(body[2:])
            if hours <= 14 and minutes < 60:
                return timezone(sign * timedelta(hours=hours, minutes=minutes))
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _date_format(order: str, separator: str) -> str:
    return {
        ("YMD", "-"): "%Y-%m-%d",
        ("YMD", "/"): "%Y/%m/%d",
        ("YMD", "."): "%Y.%m.%d",
        ("DMY", "-"): "%d-%m-%Y",
        ("DMY", "/"): "%d/%m/%Y",
        ("DMY", "."): "%d.%m.%Y",
        ("MDY", "-"): "%m-%d-%Y",
        ("MDY", "/"): "%m/%d/%Y",
        ("MDY", "."): "%m.%d.%Y",
    }.get((order, separator))


def _parse_timestamp_values(
    date_values: pd.Series,
    time_values: pd.Series | None,
    header_text: str,
    explicit_timezone: str | None,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    warnings: list[str] = []
    texts: list[str] = []
    for index, value in enumerate(date_values.tolist()):
        if _is_empty(value):
            texts.append("")
            continue
        date_text = str(value).strip()
        if time_values is not None:
            time_value = time_values.iloc[index]
            if _is_empty(time_value):
                texts.append("")
                continue
            date_text = f"{date_text} {str(time_value).strip()}"
        texts.append(date_text)
    text_series = pd.Series(texts, index=date_values.index, dtype=object)

    date_part_values = [_strip_time(text) for text in texts if text]
    order_info = _detect_date_order(
        date_part_values, header_text=header_text, override=get_path(config, "time.date_order", None)
    )
    time_info = _detect_time_format([value for value in (time_values.tolist() if time_values is not None else []) if not _is_empty(value)])
    if time_values is None:
        # Infer time presence from the timestamp text itself.
        inferred_time = _detect_time_format(
            [re.split(r"[ T]", text, maxsplit=1)[1] for text in texts if len(re.split(r"[ T]", text, maxsplit=1)) > 1]
        )
        if inferred_time.get("format"):
            time_info = inferred_time

    value_tz = _detect_value_timezone(texts)
    header_tz = _detect_header_timezone(header_text, config)
    config_tz = get_path(config, "time.default_timezone", None)

    timezone_value: str | None = None
    timezone_source: str | None = None
    timezone_reason: str | None = None
    if explicit_timezone:
        timezone_value = explicit_timezone
        timezone_source = "parameter"
        timezone_reason = "Time zone supplied explicitly by the caller."
    elif value_tz.get("timezone"):
        timezone_value = value_tz["timezone"]
        timezone_source = "values"
        timezone_reason = value_tz["reason"]
    elif header_tz.get("timezone"):
        timezone_value = header_tz["timezone"]
        timezone_source = "header"
        timezone_reason = header_tz["reason"]
    elif config_tz:
        timezone_value = str(config_tz)
        timezone_source = "config"
        timezone_reason = "Time zone supplied by configuration."
    else:
        timezone_reason = header_tz.get("reason") if header_tz.get("source") == "header" else "No time zone could be established."

    separator = next((char for char in "-/." if any(char in _strip_time(text) for text in texts if text)), "-")
    order = order_info.get("order")
    date_format = _date_format(order, separator) if order else None
    time_format = time_info.get("format")
    if time_values is not None and time_format is None:
        warnings.append(time_info.get("reason", "Separate time column format is unresolved."))
    pandas_format = None
    if date_format and time_format:
        pandas_format = f"{date_format} {time_format}"
    elif date_format:
        pandas_format = date_format

    format_text = None
    if order and date_format:
        date_label = {
            "YMD": f"YYYY{separator}MM{separator}DD",
            "DMY": f"DD{separator}MM{separator}YYYY",
            "MDY": f"MM{separator}DD{separator}YYYY",
        }[order]
        format_text = date_label + (f" {time_info.get('text')}" if time_info.get("text") else "")

    local = pd.Series(pd.NaT, index=date_values.index, dtype="datetime64[ns]")
    utc = pd.Series(pd.NaT, index=date_values.index, dtype="datetime64[ns, UTC]")
    parse_errors = 0

    if order is None:
        warnings.append(order_info.get("reason", "Date order is unresolved."))
        return utc, local, {
            "status": "unresolved",
            "format": format_text,
            "pandas_format": pandas_format,
            "timezone": timezone_value,
            "timezone_source": timezone_source,
            "timezone_reason": timezone_reason,
            "day_month_order": None,
            "date_order_reason": order_info.get("reason"),
            "ambiguous_reasons": [order_info.get("reason", "Date order is unresolved.")],
            "value_time_zone": value_tz,
            "header_time_zone": header_tz,
            "parse_errors": int(text_series.notna().sum()),
            "warnings": warnings,
        }

    if pandas_format is None and not value_tz.get("timezone"):
        reason = "Timestamp text did not match a supported date/time format."
        warnings.append(reason)
        return utc, local, {
            "status": "unresolved",
            "format": format_text,
            "pandas_format": pandas_format,
            "timezone": timezone_value,
            "timezone_source": timezone_source,
            "timezone_reason": timezone_reason,
            "day_month_order": order,
            "date_order_reason": order_info.get("reason"),
            "ambiguous_reasons": [reason],
            "value_time_zone": value_tz,
            "header_time_zone": header_tz,
            "parse_errors": int(text_series.notna().sum()),
            "warnings": warnings,
        }

    if pandas_format and not value_tz.get("timezone"):
        parse_series = text_series
        if " " in pandas_format:
            parse_series = parse_series.str.replace("T", " ", regex=False)
        parsed = pd.to_datetime(parse_series, format=pandas_format, errors="coerce")
    else:
        # Explicit offsets require utc=True; ISO values can also be parsed here.
        parse_series = text_series.str.replace("T", " ", regex=False)
        parsed = pd.to_datetime(parse_series, errors="coerce", utc=bool(value_tz.get("timezone")))
    parse_errors = int(parsed.isna().sum() - text_series.eq("").sum())

    if timezone_value is None:
        # Local time is retained, but no UTC value is fabricated.
        local = pd.Series(parsed, index=date_values.index)
        if getattr(local.dt, "tz", None) is not None:
            local = local.dt.tz_localize(None)
        warnings.append("Time zone is unresolved; timestamps were not converted to UTC.")
        return utc, local, {
            "status": "unresolved",
            "format": format_text,
            "pandas_format": pandas_format,
            "timezone": None,
            "timezone_source": None,
            "timezone_reason": timezone_reason,
            "day_month_order": order,
            "date_order_reason": order_info.get("reason"),
            "ambiguous_reasons": [timezone_reason or "Time zone is unresolved."],
            "value_time_zone": value_tz,
            "header_time_zone": header_tz,
            "parse_errors": parse_errors,
            "warnings": warnings,
        }

    if parsed.dt.tz is not None:
        utc = parsed.dt.tz_convert("UTC")
        local = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    else:
        tzinfo = _timezone_from_text(str(timezone_value))
        if tzinfo is None:
            local = pd.Series(parsed, index=date_values.index)
            warnings.append(f"Time zone {timezone_value!r} could not be resolved by the runtime tz database.")
            return utc, local, {
                "status": "unresolved",
                "format": format_text,
                "pandas_format": pandas_format,
                "timezone": timezone_value,
                "timezone_source": timezone_source,
                "timezone_reason": timezone_reason,
                "day_month_order": order,
                "date_order_reason": order_info.get("reason"),
                "ambiguous_reasons": [f"Time zone {timezone_value!r} unavailable."],
                "value_time_zone": value_tz,
                "header_time_zone": header_tz,
                "parse_errors": parse_errors,
                "warnings": warnings,
            }
        try:
            localized = parsed.dt.tz_localize(tzinfo, ambiguous="raise", nonexistent="raise")
        except (TypeError, ValueError) as exc:
            local = pd.Series(parsed, index=date_values.index)
            warnings.append(f"Timestamp localization failed: {exc}")
            return utc, local, {
                "status": "unresolved",
                "format": format_text,
                "pandas_format": pandas_format,
                "timezone": timezone_value,
                "timezone_source": timezone_source,
                "timezone_reason": timezone_reason,
                "day_month_order": order,
                "date_order_reason": order_info.get("reason"),
                "ambiguous_reasons": [f"Localization failed: {exc}"],
                "value_time_zone": value_tz,
                "header_time_zone": header_tz,
                "parse_errors": parse_errors,
                "warnings": warnings,
            }
        utc = localized.dt.tz_convert("UTC")
        local = pd.Series(parsed, index=date_values.index)

    return utc, local, {
        "status": "resolved",
        "format": format_text,
        "pandas_format": pandas_format,
        "timezone": timezone_value,
        "timezone_source": timezone_source,
        "timezone_reason": timezone_reason,
        "day_month_order": order,
        "date_order_reason": order_info.get("reason"),
        "ambiguous_reasons": [],
        "value_time_zone": value_tz,
        "header_time_zone": header_tz,
        "parse_errors": parse_errors,
        "warnings": warnings,
    }


def _detect_timestamp(
    frame: pd.DataFrame,
    labels: list[str],
    vocab: dict[str, Any],
    config: dict[str, Any],
    explicit_timezone: str | None,
    units_by_label: dict[str, str] | None = None,
) -> dict[str, Any]:
    minimum = float(get_path(config, "mapping.minimum_candidate_score", 0.52))
    candidates: list[dict[str, Any]] = []
    for index, column in enumerate(frame.columns):
        label = labels[index] if index < len(labels) else str(column)
        header_scores = score_header_roles(label, vocab, config)
        header_score = next((item["score"] for item in header_scores if item["role"] == "timestamp"), 0.0)
        date_ratio = _date_like_ratio(frame[column])
        time_ratio = _time_like_ratio(frame[column])
        if header_score >= minimum or date_ratio >= 0.80 or (time_ratio >= 0.80 and header_score >= 0.45):
            candidates.append(
                {
                    "column": str(column),
                    "label": label,
                    "header_score": header_score,
                    "date_like_ratio": round(date_ratio, 4),
                    "time_like_ratio": round(time_ratio, 4),
                    "score": round(max(header_score, date_ratio, time_ratio * 0.8), 4),
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["column"]))

    if not candidates:
        return {
            "status": "not_found",
            "columns": [],
            "date_column": None,
            "time_column": None,
            "format": None,
            "timezone": None,
            "timezone_source": None,
            "day_month_order": None,
            "sampling_interval_seconds": None,
            "ambiguity": ["No timestamp column was detected."],
            "warnings": ["No timestamp column was detected."],
        }

    date_candidates = [item for item in candidates if item["date_like_ratio"] >= 0.60]
    time_candidates = [item for item in candidates if item["time_like_ratio"] >= 0.60 and item["date_like_ratio"] < 0.60]
    date_candidate = date_candidates[0] if date_candidates else candidates[0]
    time_candidate = None
    if time_candidates and time_candidates[0]["column"] != date_candidate["column"]:
        time_candidate = time_candidates[0]

    ambiguous: list[str] = []
    if len(date_candidates) > 1:
        ambiguous.append(
            "Multiple date-like columns detected; the highest-scoring column was used and the others remain unresolved."
        )
    if date_candidate["date_like_ratio"] < 0.60 and date_candidate["header_score"] < minimum:
        ambiguous.append("Timestamp column was detected by header only; value evidence is weak.")

    date_series = frame[date_candidate["column"]]
    time_series = frame[time_candidate["column"]] if time_candidate else None
    utc, local, info = _parse_timestamp_values(
        date_series,
        time_series,
        # A units row such as "dd-mm-yyyy hh:mm" is explicit date-order evidence.
        header_text=" ".join(filter(None, [date_candidate["label"], (units_by_label or {}).get(date_candidate["label"])])),
        explicit_timezone=explicit_timezone,
        config=config,
    )

    interval_seconds = None
    interval_text = None
    valid_utc = utc.dropna()
    minimum_timestamps = int(get_path(config, "time.minimum_timestamps_for_interval", 3))
    if len(valid_utc) >= minimum_timestamps:
        unique = pd.Series(valid_utc.unique()).sort_values()
        diffs = unique.diff().dropna().dt.total_seconds()
        diffs = diffs[diffs > 0]
        if len(diffs):
            interval_seconds = float(diffs.median())
            interval_seconds = round(interval_seconds, int(get_path(config, "time.sampling_interval_round_seconds", 1)))
            interval_text = _human_interval(interval_seconds)

    columns = [date_candidate["column"]] + ([time_candidate["column"]] if time_candidate else [])
    ambiguity = list(info.get("ambiguous_reasons", [])) + ambiguous
    return {
        "_utc_series": utc,
        "_local_series": local,
        "status": info.get("status", "unresolved") if not ambiguity else "unresolved",
        "columns": columns,
        "date_column": date_candidate["column"],
        "time_column": time_candidate["column"] if time_candidate else None,
        "format": info.get("format"),
        "pandas_format": info.get("pandas_format"),
        "timezone": info.get("timezone"),
        "timezone_source": info.get("timezone_source"),
        "timezone_reason": info.get("timezone_reason"),
        "day_month_order": info.get("day_month_order"),
        "date_order_reason": info.get("date_order_reason"),
        "value_time_zone": info.get("value_time_zone"),
        "header_time_zone": info.get("header_time_zone"),
        "sampling_interval_seconds": interval_seconds,
        "sampling_interval_text": interval_text,
        "valid_timestamps": int(utc.notna().sum()),
        "invalid_timestamps": int(len(utc) - utc.notna().sum()),
        "parse_errors": int(info.get("parse_errors", 0)),
        "ambiguity": ambiguity,
        "warnings": list(info.get("warnings", [])),
        "candidate_columns": candidates,
    }


def _human_interval(seconds: float) -> str:
    if seconds % 3600 == 0:
        return f"{int(seconds // 3600)} h"
    if seconds % 60 == 0:
        return f"{int(seconds // 60)} min"
    return f"{seconds:g} s"


def _build_table(
    raw: pd.DataFrame,
    source_file: str,
    sheet_name: str | None,
    vocab: dict[str, Any],
    config: dict[str, Any],
    explicit_timezone: str | None,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> TableData:
    header_info = detect_header_row(raw, vocab, config)
    header_row = int(header_info["header_row"])
    warnings = list(header_info.get("warnings", []))

    header_values = raw.iloc[header_row].tolist() if len(raw) else []
    raw_headers, display, aliases = _unique_headers(header_values)
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = list(aliases.keys())
    data = data.reset_index(drop=True)

    # Skip leading units/metadata rows (and blank spacer rows) under the header,
    # keeping the units as column metadata. A row with any numeric value is data.
    column_units: dict[str, str] = {}
    unit_rows_skipped = 0
    leading = 0
    while leading < min(len(data), 4):
        values = data.iloc[leading].tolist()
        if all(_is_empty(value) for value in values):
            leading += 1
            continue
        if not _is_unit_row(values):
            break
        for column, value in zip(data.columns, values):
            if not _is_empty(value) and str(column) not in column_units:
                column_units[str(column)] = str(value).strip()
        unit_rows_skipped += 1
        leading += 1
    if unit_rows_skipped:
        data = data.iloc[leading:].reset_index(drop=True)
        warnings.append(
            f"{unit_rows_skipped} units row(s) under the header were used as column units, not data."
        )

    dropped_rows = 0
    dropped_columns = 0
    dropped_column_names: list[str] = []
    if bool(get_path(config, "ingestion.drop_fully_empty_rows", True)):
        empty_rows = data.apply(lambda row: all(_is_empty(value) for value in row.tolist()), axis=1)
        dropped_rows = int(empty_rows.sum())
        data = data.loc[~empty_rows].reset_index(drop=True)
    if bool(get_path(config, "ingestion.drop_fully_empty_columns", True)):
        empty_columns = [column for column in data.columns if all(_is_empty(value) for value in data[column].tolist())]
        dropped_columns = len(empty_columns)
        dropped_column_names = [aliases.get(str(column), str(column)) for column in empty_columns]
        if empty_columns:
            data = data.drop(columns=empty_columns)
            for column in empty_columns:
                aliases.pop(column, None)
            display = [aliases.get(str(column), "<dropped empty column>") for column in data.columns]

    typed = pd.DataFrame(index=data.index)
    for column in data.columns:
        label = aliases.get(str(column), str(column))
        typed[column] = _infer_series(data[column], warnings, label)
    data = typed

    labels = [aliases.get(str(column), str(column)) for column in data.columns]
    units_by_label = {aliases.get(str(column), str(column)): unit for column, unit in column_units.items()}
    timestamp_info = _detect_timestamp(data, labels, vocab, config, explicit_timezone, units_by_label)
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

    if timestamp_info.get("status") != "resolved":
        warnings.append("Timestamp interpretation is unresolved; see timestamp.ambiguity.")

    return TableData(
        source_file=source_file,
        sheet_name=sheet_name,
        frame=data,
        original_columns=labels,
        raw_headers=raw_headers,
        column_aliases=aliases,
        header=header_info,
        layout=layout,
        timestamp=timestamp_info,
        warnings=warnings,
        dropped_empty_rows=dropped_rows,
        dropped_empty_columns=dropped_columns,
        dropped_empty_column_names=dropped_column_names,
        encoding=encoding,
        delimiter=delimiter,
        column_units={column: unit for column, unit in column_units.items() if column in data.columns},
        unit_rows_skipped=unit_rows_skipped,
    )


def _raw_timestamp_text(frame: pd.DataFrame, timestamp_info: dict[str, Any]) -> pd.Series:
    date_column = timestamp_info.get("date_column")
    time_column = timestamp_info.get("time_column")
    if not date_column or date_column not in frame.columns:
        return pd.Series([np.nan] * len(frame), index=frame.index, dtype=object)
    dates = frame[date_column].map(lambda value: "" if _is_empty(value) else str(value).strip())
    if time_column and time_column in frame.columns:
        times = frame[time_column].map(lambda value: "" if _is_empty(value) else str(value).strip())
        return dates.where(times.eq(""), dates + " " + times)
    return dates.where(dates.ne(""), np.nan)


def read_csv(
    path: str | Path,
    config: dict[str, Any] | None = None,
    vocab: dict[str, Any] | None = None,
    timezone: str | None = None,
) -> TableData:
    """Read one CSV file and return its typed table plus discovery metadata."""

    config = config or load_defaults()
    vocab = vocab or load_vocab()
    path = Path(path)
    raw, encoding, delimiter = _read_csv_raw(path, config)
    return _build_table(
        raw,
        source_file=str(path),
        sheet_name=None,
        vocab=vocab,
        config=config,
        explicit_timezone=timezone,
        encoding=encoding,
        delimiter=delimiter,
    )


def read_excel(
    path: str | Path,
    config: dict[str, Any] | None = None,
    vocab: dict[str, Any] | None = None,
    timezone: str | None = None,
) -> list[TableData]:
    """Read every sheet in an .xlsx workbook."""

    config = config or load_defaults()
    vocab = vocab or load_vocab()
    path = Path(path)
    sheets = _read_excel_raw(path)
    return [
        _build_table(
            raw,
            source_file=str(path),
            sheet_name=sheet,
            vocab=vocab,
            config=config,
            explicit_timezone=timezone,
        )
        for sheet, raw in sheets.items()
    ]


def ingest_file(
    path: str | Path,
    config: dict[str, Any] | None = None,
    vocab: dict[str, Any] | None = None,
    timezone: str | None = None,
) -> IngestionResult:
    """Ingest a CSV or .xlsx file without downloading anything."""

    config = config or load_defaults()
    vocab = vocab or load_vocab()
    path = Path(path)
    suffix = path.suffix.lower()
    if not path.exists():
        return IngestionResult(source_file=str(path), file_type=suffix.lstrip("."), errors=[f"File does not exist: {path}"])
    try:
        if suffix == ".csv":
            table = read_csv(path, config=config, vocab=vocab, timezone=timezone)
            return IngestionResult(source_file=str(path), file_type="csv", tables=[table])
        if suffix == ".xlsx":
            tables = read_excel(path, config=config, vocab=vocab, timezone=timezone)
            warnings = []
            if not tables:
                warnings.append("Workbook contains no sheets.")
            return IngestionResult(source_file=str(path), file_type="xlsx", tables=tables, warnings=warnings)
        if suffix == ".pdf":
            return IngestionResult(source_file=str(path), file_type="pdf", errors=["PDF ingestion is intentionally not implemented."])
        return IngestionResult(
            source_file=str(path),
            file_type=suffix.lstrip("."),
            errors=[f"Unsupported file type {suffix!r}; supported types are .csv and .xlsx."],
        )
    except Exception as exc:  # surfaced as a structured error, never hidden
        return IngestionResult(
            source_file=str(path),
            file_type=suffix.lstrip("."),
            errors=[f"{type(exc).__name__}: {exc}"],
        )


def inspect_file(
    path: str | Path,
    config: dict[str, Any] | None = None,
    vocab: dict[str, Any] | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Return only the structure/manifest view for a file."""

    return ingest_file(path, config=config, vocab=vocab, timezone=timezone).to_manifest()
