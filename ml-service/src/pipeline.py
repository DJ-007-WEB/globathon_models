"""End-to-end pipeline entry point.

The orchestration lives in :mod:`src.service`; this module keeps the historical
``run_pipeline`` name and the command-line interface as thin compatibility
wrappers around the public ``analyze`` boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import load_defaults
from .service import analyze


def run_pipeline(
    data_path: str | Path,
    output_path: str | Path | None = None,
    *,
    config: dict[str, Any] | None = None,
    mode: str = "auto",
    timezone: str | None = None,
    interval_minutes: float | None = None,
    plant_id: str | None = None,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """Run the project pipeline through the public analysis boundary."""

    return analyze(
        data_path,
        config=config,
        output_path=output_path,
        mode=mode,
        timezone=timezone,
        interval_minutes=interval_minutes,
        plant_id=plant_id,
        sheet_name=sheet_name,
    )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the ML analysis pipeline end-to-end.")
    parser.add_argument(
        "--inputs",
        required=True,
        help="Scenario directory or one CSV/XLSX operating-data file.",
    )
    parser.add_argument("--output", required=True, help="Output JSON path for the analysis result.")
    parser.add_argument(
        "--mode",
        choices=("auto", "snapshot", "full"),
        default="auto",
        help="Analysis mode; auto selects snapshot for a single timestamp.",
    )
    parser.add_argument("--timezone", default=None, help="Explicit IANA time zone, e.g. Europe/Berlin.")
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=None,
        help="Explicit interval duration; otherwise derived from timestamps.",
    )
    parser.add_argument("--plant-id", default=None, help="Optional plant identifier for the output.")
    parser.add_argument("--sheet", default=None, help="Worksheet name when the input is XLSX.")
    args = parser.parse_args()

    config = load_defaults()
    payload = run_pipeline(
        args.inputs,
        args.output,
        config=config,
        mode=args.mode,
        timezone=args.timezone,
        interval_minutes=args.interval_minutes,
        plant_id=args.plant_id,
        sheet_name=args.sheet,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("analysis_status") in {"success", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(_main())
