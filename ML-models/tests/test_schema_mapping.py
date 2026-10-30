from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion import ingest_file
from src.schema_mapping import map_table
from src.validation import validate_table


def _ingest(tmp_path: Path, text: str):
    path = tmp_path / "fixture.csv"
    path.write_text(text, encoding="utf-8")
    return ingest_file(path).tables[0]


def test_mixed_units_are_converted_from_header_text(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,ac_power_w,interval_energy_wh,capacity_kwp,module_temp_f\n"
        "2024-01-01T00:00:00Z,1000,500,10,68\n"
        "2024-01-01T00:15:00Z,2000,1000,10,77\n",
    )
    mapping = map_table(table)
    fields = {field["source_column"]: field for field in mapping.fields}

    assert fields["ac_power_w"]["canonical_role"] == "power_ac"
    assert fields["ac_power_w"]["detected_unit"] == "W"
    assert fields["ac_power_w"]["conversion"]["factor"] == pytest.approx(0.001)
    assert fields["interval_energy_wh"]["canonical_role"] == "energy_interval"
    assert fields["interval_energy_wh"]["detected_unit"] == "Wh"
    assert fields["interval_energy_wh"]["conversion"]["factor"] == pytest.approx(0.001)
    assert fields["capacity_kwp"]["canonical_role"] == "capacity"
    assert fields["capacity_kwp"]["detected_unit"] == "kWp"
    assert fields["module_temp_f"]["canonical_role"] == "module_temperature"
    assert fields["module_temp_f"]["conversion"]["factor"] == pytest.approx(5.0 / 9.0)
    assert fields["module_temp_f"]["canonical_unit"] == "C"


def test_poa_and_ghi_are_distinguished(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,poa_irradiance_wm2,ghi_wm2\n"
        "2024-01-01T00:00:00Z,0,0\n"
        "2024-01-01T00:15:00Z,500,450\n",
    )
    mapping = map_table(table)
    assert mapping.role_to_columns["irradiance_poa"] == ["poa_irradiance_wm2"]
    assert mapping.role_to_columns["irradiance_ghi"] == ["ghi_wm2"]


def test_generic_headers_remain_unresolved_with_reasons(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,power,irradiance,temperature,mystery_signal\n"
        "2024-01-01T00:00:00Z,1,100,20,7\n"
        "2024-01-01T00:15:00Z,2,200,21,8\n",
    )
    mapping = map_table(table)
    unresolved = {field["source_column"] for field in mapping.fields if field["unresolved"]}
    assert {"power", "irradiance", "temperature", "mystery_signal"}.issubset(unresolved)
    reasons = {
        field["source_column"]: " ".join(field["unresolved_reasons"]).lower()
        for field in mapping.fields
    }
    assert "generic" in reasons["power"] or "distinguish" in reasons["power"]
    assert "no vocabulary" in reasons["mystery_signal"]


def test_manifest_has_required_traceability_fields(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,1\n"
        "2024-01-01T00:15:00Z,2\n",
    )
    manifest = map_table(table).to_dict()
    assert manifest["mapping_version"]
    field = next(item for item in manifest["fields"] if item["source_column"] == "ac_power_kw")
    for key in [
        "source_file",
        "source_column",
        "canonical_role",
        "detected_unit",
        "conversion",
        "confidence",
        "validation_result",
        "warnings",
        "unresolved",
        "unresolved_reasons",
        "mapping_version",
        "provenance",
    ]:
        assert key in field


def test_power_above_documented_capacity_is_flagged(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,capacity_kwp,ac_power_kw\n"
        "2024-01-01T00:00:00Z,10,20\n"
        "2024-01-01T00:15:00Z,10,21\n",
    )
    mapping = map_table(table)
    fields = {field["source_column"]: field for field in mapping.fields}
    assert fields["capacity_kwp"]["canonical_role"] == "capacity"
    assert fields["ac_power_kw"]["canonical_role"] == "power_ac"
    assert fields["ac_power_kw"]["validation_result"]["status"] == "warning"
    report = validate_table(table, mapping)
    over_capacity = [check for check in report["checks"] if check["check_id"] == "power_above_capacity"]
    assert over_capacity and over_capacity[0]["count"] == 2


def test_long_device_column_and_energy_semantics(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,inverter_id,cumulative_energy_kwh,interval_energy_kwh\n"
        "2024-01-01T00:00:00Z,INV-1,100,1\n"
        "2024-01-01T00:15:00Z,INV-1,101,1\n",
    )
    mapping = map_table(table)
    assert mapping.role_to_columns["device_id"] == ["inverter_id"]
    assert mapping.role_to_columns["energy_cumulative"] == ["cumulative_energy_kwh"]
    assert mapping.role_to_columns["energy_interval"] == ["interval_energy_kwh"]
    assert table.layout["layout_type"] == "long"


def test_quantity_names_are_not_mistaken_for_device_ids(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,inverter_id,inverter_efficiency,ac_power_kw\n"
        "2024-01-01T00:00:00Z,INV-1,0.97,5\n"
        "2024-01-01T00:15:00Z,INV-1,0.98,6\n",
    )
    mapping = map_table(table)
    fields = {field["source_column"]: field for field in mapping.fields}
    assert fields["inverter_id"]["canonical_role"] == "device_id"
    assert fields["inverter_efficiency"]["canonical_role"] == "inverter_efficiency"
    assert fields["inverter_efficiency"]["canonical_role"] != "device_id"


def test_wide_device_type_token_is_preserved(tmp_path):
    table = _ingest(
        tmp_path,
        "timestamp,INV-01 AC Power (kW),INV-01 Module Temp (C),"
        "INV-02 AC Power (kW),INV-02 Module Temp (C)\n"
        "2024-01-01T00:00:00Z,0,20,0,20\n"
        "2024-01-01T00:15:00Z,5,30,4,31\n",
    )
    mapping = map_table(table)
    assert table.layout["layout_type"] == "wide"
    assert set(table.layout["devices"]) == {"inv-01", "inv-02"}
    assert mapping.role_to_columns["power_ac"] == ["INV-01 AC Power (kW)", "INV-02 AC Power (kW)"]
