"""Export labelled synthetic reports for the frontend's read-only preview workspace.

Generates scenarios with the synthetic generator, runs each through the real
deterministic pipeline and writes the results in the backend's saved-analysis
shape to ``frontend/public/preview/``. No AI explanation is included: the
preview states that narrative needs a connected backend and local model.

Run from ml-service/:  python scripts/export_preview_reports.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.service import analyze  # noqa: E402
from src.synthetic import GeneratorConfig, generate_scenarios, write_scenarios  # noqa: E402

OUT = ROOT.parent / "frontend" / "public" / "preview"
PLANT = {"plant_id": "synthetic-plant-a", "name": "Synthetic plant A", "location": None,
         "capacity_kw": None, "timezone": "UTC", "created_at": None, "updated_at": None}
# Report timestamps are labels for the preview list, not measurements.
CREATED = ["2026-01-14T15:05:00+00:00", "2026-01-12T09:20:00+00:00", "2026-01-09T11:40:00+00:00"]


def main() -> int:
    config = GeneratorConfig(seed=42, n_scenarios=3, days=4, inverter_count=3)
    scenarios = generate_scenarios(config)
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = []
    with tempfile.TemporaryDirectory() as tmp:
        write_scenarios(scenarios, Path(tmp))
        for index, directory in enumerate(sorted(p for p in Path(tmp).iterdir() if p.is_dir())):
            filename = f"synthetic_scenario_{index + 1:03d}.csv"
            ml = analyze(directory, mode="full", plant_id=PLANT["plant_id"])
            # Report the operating file under the preview name; other inputs keep their names.
            ml["request"]["source_files"] = [filename] + ml["request"]["source_files"][1:]
            request_id = f"preview-{index + 1:03d}"
            summary = {"request_id": request_id, "plant_id": PLANT["plant_id"], "filename": filename,
                       "analysis_status": ml["analysis_status"], "analysis_mode": ml["analysis_mode"],
                       "created_at": CREATED[index % len(CREATED)]}
            detail = {**summary, "result": {"request_id": request_id, "plant_id": PLANT["plant_id"],
                                            "model": "none", "analysis": None, "ml_analysis": ml,
                                            "analysis_mode": ml["analysis_mode"]}}
            (OUT / f"{request_id}.json").write_text(json.dumps(detail, indent=1, default=str), encoding="utf-8")
            summaries.append(summary)
            print(request_id, filename, ml["analysis_status"], ml["summary"][:110])
    (OUT / "index.json").write_text(json.dumps({"plants": [PLANT], "analyses": summaries,
                                                "note": "Synthetic scenarios processed by the real SolarSleuth ML pipeline."},
                                               indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
