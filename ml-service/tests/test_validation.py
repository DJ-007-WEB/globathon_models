from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingestion import ingest_file
from src.schema_mapping import map_table
from src.validation import validate_frame, validate_table


def _run(tmp_path: Path, text: str, **kwargs):
    path = tmp_path / "fixture.csv"
    path.write_text(text, encoding="utf-8")
    table = ingest_file(path).tables[0]
    mapping = map_table(table)
    return table, mapping, validate_table(table, mapping, **kwargs)


def _by_id(report, check_id):
    return [check for check in report["checks"] if check["check_id"] == check_id]


def test_validate_frame_compatibility(sample_frame):
    result = validate_frame(sample_frame)
    assert result["rows"] == 2
    assert result["valid"] is True


def test_duplicates_out_of_order_and_gaps(tmp_path):
    table, _, report = _run(
        tmp_path,
        "timestamp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,1\n"
        "2024-01-01T00:15:00Z,2\n"
        "2024-01-01T00:15:00Z,3\n"
        "2024-01-01T00:05:00Z,4\n"
        "2024-01-01T01:00:00Z,5\n",
    )
    assert table.timestamp["status"] == "resolved"
    duplicates = _by_id(report, "duplicate_timestamps")[0]
    order = _by_id(report, "out_of_order_timestamps")[0]
    gaps = _by_id(report, "time_gaps")[0]
    assert duplicates["count"] == 1
    assert order["count"] == 1
    assert gaps["count"] >= 1
    assert report["status"] == "fail"


def test_cumulative_counter_reset_is_flagged_not_repaired(tmp_path):
    table, mapping, report = _run(
        tmp_path,
        "timestamp,inverter_id,cumulative_energy_kwh\n"
        "2024-01-01T00:00:00Z,INV-1,100\n"
        "2024-01-01T00:15:00Z,INV-1,101\n"
        "2024-01-01T00:30:00Z,INV-1,99\n",
    )
    resets = _by_id(report, "cumulative_counter_reset")
    assert resets
    assert resets[0]["count"] == 1
    assert "INV-1" in resets[0]["affected_devices"]
    assert table.frame["cumulative_energy_kwh"].iloc[2] == 99


def test_missing_values_are_nan_and_flatlines_are_flagged(tmp_path):
    table, _, report = _run(
        tmp_path,
        "timestamp,ghi_wm2,ac_power_kw\n"
        "2024-01-01T12:00:00Z,500,5\n"
        "2024-01-01T12:15:00Z,,5\n"
        "2024-01-01T12:30:00Z,500,5\n"
        "2024-01-01T12:45:00Z,500,5\n"
        "2024-01-01T13:00:00Z,500,5\n"
        "2024-01-01T13:15:00Z,500,5\n"
        "2024-01-01T13:30:00Z,500,5\n"
        "2024-01-01T13:45:00Z,500,5\n",
    )
    assert pd.isna(table.frame["ghi_wm2"].iloc[1])
    assert table.frame["ghi_wm2"].iloc[1] != 0
    missing = _by_id(report, "missing_values")[0]
    assert missing["count"] == 1
    flatlines = _by_id(report, "suspicious_flatline")
    assert any(item["details"]["column"] == "ac_power_kw" for item in flatlines)


def test_negative_power_is_flagged(tmp_path):
    _, _, report = _run(
        tmp_path,
        "timestamp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,-1\n"
        "2024-01-01T00:15:00Z,5\n",
    )
    negative = _by_id(report, "negative_power")
    assert negative and negative[0]["count"] == 1
    assert report["status"] == "fail"


def test_night_time_generation_screening(tmp_path):
    table, mapping, report = _run(
        tmp_path,
        "timestamp,ac_power_kw,ghi_wm2\n"
        "2024-01-01T00:00:00Z,5,0\n"
        "2024-01-01T00:15:00Z,5,0\n"
        "2024-01-01T00:30:00Z,5,0\n"
        "2024-01-01T00:45:00Z,5,0\n",
        location={"latitude": 0.0, "longitude": 0.0},
    )
    night = [check for check in report["checks"] if check["check_id"].startswith("night_time_power")]
    assert night and night[0]["count"] == 4
    assert "NOAA" in night[0]["details"]["method"]


def test_timezone_ambiguity_is_reported(tmp_path):
    table, _, report = _run(
        tmp_path,
        "timestamp,ac_power_kw\n"
        "2024-01-01 00:00:00,1\n"
        "2024-01-01 00:15:00,2\n",
    )
    assert table.timestamp["status"] == "unresolved"
    ambiguity = _by_id(report, "timestamp_ambiguity")
    assert ambiguity and ambiguity[0]["status"] == "warning"
    assert any("UTC" in item for item in report["limitations"])


def test_long_layout_timestamps_are_checked_per_device(tmp_path):
    _, _, report = _run(
        tmp_path,
        "timestamp,inverter_id,ac_power_kw\n"
        "2024-01-01T00:00:00Z,A,1\n"
        "2024-01-01T00:15:00Z,A,2\n"
        "2024-01-01T00:30:00Z,A,3\n"
        "2024-01-01T00:00:00Z,B,1\n"
        "2024-01-01T00:15:00Z,B,2\n"
        "2024-01-01T00:30:00Z,B,3\n",
    )
    assert _by_id(report, "duplicate_timestamps")[0]["count"] == 0
    assert _by_id(report, "out_of_order_timestamps")[0]["count"] == 0
    assert _by_id(report, "time_gaps")[0]["count"] == 0
