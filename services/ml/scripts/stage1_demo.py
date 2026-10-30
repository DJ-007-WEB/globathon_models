"""Stage 1 demo: ingestion + mapping + validation on a synthetic fixture.

This script writes only to the git-ignored ``artifacts/stage1_demo/`` folder.
The fixture is synthetic and is not a real-plant accuracy test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion import ingest_file  # noqa: E402
from src.schema_mapping import map_table  # noqa: E402
from src.validation import validate_table  # noqa: E402

FIXTURE_TEXT = (
    "timestamp,INV-01 AC Power (kW),INV-01 POA Irradiance (W/m2),INV-01 Module Temp (C),"
    "INV-02 AC Power (kW),INV-02 POA Irradiance (W/m2),INV-02 Module Temp (C),Site GHI (W/m2)\n"
    "2024-06-01T00:00:00Z,0,0,22,0,0,22,0\n"
    "2024-06-01T00:15:00Z,42,600,38,40,590,39,520\n"
    "2024-06-01T00:30:00Z,45,650,41,,640,42,560\n"
    "2024-06-01T00:45:00Z,44,640,40,43,630,41,550\n"
    "2024-06-01T01:00:00Z,44,640,40,43,630,41,550\n"
    "2024-06-01T01:15:00Z,44,640,40,43,630,41,550\n"
    "2024-06-01T01:30:00Z,44,640,40,43,630,41,550\n"
    "2024-06-01T01:45:00Z,44,640,40,43,630,41,550\n"
    "2024-06-01T02:00:00Z,44,640,40,43,630,41,550\n"
)


def main() -> None:
    demo_dir = PROJECT_ROOT / "artifacts" / "stage1_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    fixture = demo_dir / "plant_demo.csv"
    fixture.write_text(FIXTURE_TEXT, encoding="utf-8")

    ingestion = ingest_file(fixture)
    if not ingestion.ok:
        print(json.dumps(ingestion.to_manifest(), indent=2, default=str))
        raise SystemExit(1)

    table = ingestion.tables[0]
    mapping = map_table(table)
    validation = validate_table(table, mapping)
    manifest = {
        "fixture_kind": "synthetic",
        "ingestion": ingestion.to_manifest(),
        "mapping": mapping.to_manifest(),
        "validation": validation,
    }
    manifest_path = demo_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    summary = {
        "fixture_kind": "synthetic",
        "fixture": str(fixture),
        "manifest": str(manifest_path),
        "timestamp": {
            key: table.timestamp.get(key)
            for key in ["status", "format", "timezone", "timezone_source", "sampling_interval_seconds"]
        },
        "layout": {
            key: table.layout.get(key)
            for key in ["layout_type", "device_id_source", "devices"]
        },
        "mapped_fields": [
            {
                "source_column": item["source_column"],
                "canonical_role": item["canonical_role"],
                "detected_unit": item["detected_unit"],
                "confidence": item["confidence"],
                "unresolved": item["unresolved"],
            }
            for item in mapping.fields
        ],
        "unresolved_fields": mapping.unresolved_fields,
        "validation": {
            "status": validation["status"],
            "counts": validation["counts"],
            "checks": [
                {
                    "check_id": item["check_id"],
                    "status": item["status"],
                    "count": item["count"],
                    "affected_devices": item["affected_devices"],
                }
                for item in validation["checks"]
            ],
            "limitations": validation["limitations"],
        },
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
