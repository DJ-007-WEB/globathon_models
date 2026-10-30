from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingestion import UTC_COLUMN, ingest_file


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def test_wide_layout_devices_and_utc(tmp_path):
    path = _write(
        tmp_path / "wide.csv",
        "Reading time,Array Alpha - AC Output (kW),Array Alpha - POA Irradiance (W/m2),"
        "Array Alpha - Module Temp (C),Array Beta - AC Output (kW),"
        "Array Beta - POA Irradiance (W/m2),Array Beta - Module Temp (C)\n"
        "2024-01-01T00:00:00Z,0,0,20,0,0,20\n"
        "2024-01-01T00:15:00Z,5,500,30,4,480,31\n"
        "2024-01-01T00:30:00Z,6,600,33,5,590,34\n",
    )
    result = ingest_file(path)
    assert result.ok
    table = result.tables[0]

    assert table.layout["layout_type"] == "wide"
    assert table.layout["devices"] == ["alpha", "beta"]
    assert table.layout["column_devices"]["Array Alpha - AC Output (kW)"] == "alpha"
    assert table.timestamp["status"] == "resolved"
    assert table.timestamp["timezone"] == "UTC"
    assert table.timestamp["sampling_interval_seconds"] == 900.0
    assert table.timestamp["format"] == "YYYY-MM-DD HH:MM:SS"
    assert str(table.frame[UTC_COLUMN].iloc[0]) == "2024-01-01 00:00:00+00:00"
    assert table.original_columns[0] == "Reading time"


def test_long_layout_with_unfamiliar_names(tmp_path):
    path = _write(
        tmp_path / "long.csv",
        "when,asset,ac_power_kw,poa_irradiance_wm2,module_temp_c\n"
        "2024-01-01T00:00:00Z,INV-A,0,0,20\n"
        "2024-01-01T00:15:00Z,INV-A,5,500,30\n"
        "2024-01-01T00:00:00Z,INV-B,0,0,21\n",
    )
    table = ingest_file(path).tables[0]
    assert table.layout["layout_type"] == "long"
    assert table.layout["device_column"] == "asset"
    assert set(table.layout["devices"]) == {"INV-A", "INV-B"}
    assert table.timestamp["date_column"] == "when"
    assert table.timestamp["status"] == "resolved"


def test_excel_all_sheets_are_inspected(tmp_path):
    path = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z"],
                "ac_power_kw": [0.0, 5.0],
            }
        ).to_excel(writer, sheet_name="Plant A", index=False)
        pd.DataFrame(
            {
                "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z"],
                "ac_power_kw": [1.0, 4.0],
            }
        ).to_excel(writer, sheet_name="Plant B", index=False)

    result = ingest_file(path)
    assert result.ok
    assert [table.sheet_name for table in result.tables] == ["Plant A", "Plant B"]
    assert all(table.timestamp["status"] == "resolved" for table in result.tables)


def test_header_row_detection_skips_preamble(tmp_path):
    path = _write(
        tmp_path / "preamble.csv",
        "SolarSleuth export\n"
        "generated for review\n"
        "timestamp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,0\n"
        "2024-01-01T00:15:00Z,5\n",
    )
    table = ingest_file(path).tables[0]
    assert table.header["header_row"] == 2
    assert list(table.frame.columns[:2]) == ["timestamp", "ac_power_kw"]


def test_ambiguous_date_order_is_not_guessed(tmp_path):
    path = _write(
        tmp_path / "ambiguous.csv",
        "timestamp,ac_power_kw\n"
        "03/04/2024 10:00,1.0\n"
        "03/04/2024 10:15,2.0\n",
    )
    table = ingest_file(path).tables[0]
    assert table.timestamp["status"] == "unresolved"
    assert table.timestamp["day_month_order"] is None
    assert any("day/month" in reason.lower() for reason in table.timestamp["ambiguity"])
    assert table.frame[UTC_COLUMN].isna().all()


def test_separate_date_time_and_explicit_timezone(tmp_path):
    path = _write(
        tmp_path / "separate.csv",
        "date,time,ac_power_kw\n"
        "2024-01-01,00:00,0\n"
        "2024-01-01,00:15,5\n"
        "2024-01-01,00:30,6\n",
    )
    table = ingest_file(path, timezone="UTC").tables[0]
    assert table.timestamp["status"] == "resolved"
    assert table.timestamp["date_column"] == "date"
    assert table.timestamp["time_column"] == "time"
    assert table.timestamp["sampling_interval_seconds"] == 900.0
    assert str(table.frame[UTC_COLUMN].iloc[0]) == "2024-01-01 00:00:00+00:00"


def test_missing_readings_stay_missing_not_zero(tmp_path):
    path = _write(
        tmp_path / "missing.csv",
        "timestamp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,1.0\n"
        "2024-01-01T00:15:00Z,\n"
        "2024-01-01T00:30:00Z,3.0\n",
    )
    table = ingest_file(path).tables[0]
    assert pd.isna(table.frame["ac_power_kw"].iloc[1])
    assert table.frame["ac_power_kw"].iloc[1] != 0


def test_fully_empty_source_column_is_preserved_by_default(tmp_path):
    path = _write(
        tmp_path / "empty_column.csv",
        "timestamp,ac_power_kw,spare_sensor\n"
        "2024-01-01T00:00:00Z,1,\n"
        "2024-01-01T00:15:00Z,2,\n",
    )
    table = ingest_file(path).tables[0]
    assert "spare_sensor" in table.frame.columns
    assert table.frame["spare_sensor"].isna().all()
    assert table.dropped_empty_columns == 0


def test_missing_file_is_reported_not_created(tmp_path):
    result = ingest_file(tmp_path / "absent.csv")
    assert not result.ok
    assert result.errors and "does not exist" in result.errors[0]


def test_pdf_is_not_parsed(tmp_path):
    path = _write(tmp_path / "report.pdf", "%PDF-1.4 fake")
    result = ingest_file(path)
    assert not result.ok
    assert "PDF ingestion" in result.errors[0]
