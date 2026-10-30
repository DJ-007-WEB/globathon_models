"""Private HTTP boundary for the deterministic SolarSleuth ML pipeline.

Run from ml-service/: python -m uvicorn api:app --host 127.0.0.1 --port 8002
The HTTP adapter accepts one operating-data CSV/XLSX file. The Python
pipeline's multi-file input support is intentionally not exposed by this route.
"""
from __future__ import annotations

import asyncio
import hmac
import math
import os
import tempfile
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from src.pipeline import run_pipeline

load_dotenv()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CONCURRENT_ANALYSES = max(1, int(os.getenv("MAX_CONCURRENT_ANALYSES", "2")))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN") or os.getenv("ML_SERVICE_TOKEN")
ANALYSIS_SLOTS = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

app = FastAPI(
    title="SolarSleuth Deterministic ML API",
    version="2.1.0",
    docs_url=None,
    redoc_url=None,
)


def require_service_token(token: str | None) -> None:
    """Require the backend's shared secret outside local development."""
    if not SERVICE_TOKEN:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
        return
    if not token or not hmac.compare_digest(token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal service credentials.")


def validate_upload(filename: str, content: bytes) -> None:
    """Perform cheap boundary checks before handing bytes to pandas/openpyxl."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        if not content.startswith(bytes((0x50, 0x4B, 0x03, 0x04))):
            raise HTTPException(status_code=415, detail="The XLSX file signature is invalid.")
        return
    if suffix == ".csv":
        if content.startswith((bytes((0x50, 0x4B, 0x03, 0x04)), bytes((0xD0, 0xCF, 0x11, 0xE0)))):
            raise HTTPException(status_code=415, detail="The CSV extension does not match the uploaded content.")
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="CSV files must use UTF-8 encoding.") from exc
        header = next((line for line in decoded.splitlines() if line.strip()), "")
        if not header or not any(delimiter in header for delimiter in (",", ";", chr(9))):
            raise HTTPException(status_code=422, detail="The CSV must contain a delimited header row.")
        return
    raise HTTPException(status_code=415, detail="Only CSV and XLSX operating-data files are supported.")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-deterministic-ml"}


@app.get("/ready")
async def ready() -> dict:
    # Importing the pipeline and its configuration at process start is the
    # readiness boundary; model weights are not required for the physics path.
    return {
        "status": "ready",
        "service": "solarsleuth-deterministic-ml",
        "pipeline_available": callable(run_pipeline),
    }


@app.post("/api/v1/analyze")
async def analyze_upload(
    file: UploadFile = File(...),
    plant_id: str = Form("unknown-plant"),
    mode: Literal["auto", "snapshot", "full"] = Form("auto"),
    timezone: str | None = Form(None),
    interval_minutes: float | None = Form(None),
    sheet_name: str | None = Form(None),
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
) -> dict:
    require_service_token(x_service_token)

    filename = Path((file.filename or "dataset").replace(chr(92), "/")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Only CSV and XLSX operating-data files are supported.")
    if interval_minutes is not None and (not math.isfinite(interval_minutes) or interval_minutes <= 0):
        await file.close()
        raise HTTPException(status_code=422, detail="interval_minutes must be a finite number greater than zero.")
    plant_id = plant_id.strip() or "unknown-plant"
    if len(plant_id) > 128 or (timezone is not None and len(timezone) > 64) or (sheet_name is not None and len(sheet_name) > 128):
        await file.close()
        raise HTTPException(status_code=422, detail="One or more analysis options exceed the allowed length.")

    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
    validate_upload(filename, content)

    try:
        await asyncio.wait_for(ANALYSIS_SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="ML analysis capacity is busy. Retry shortly.") from exc

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(content)
            temp_path = handle.name
        try:
            result = await run_in_threadpool(
                run_pipeline,
                temp_path,
                None,
                mode=mode,
                timezone=timezone,
                interval_minutes=interval_minutes,
                plant_id=plant_id,
                sheet_name=sheet_name,
            )
        except HTTPException:
            raise
        except Exception as exc:
            # Keep parser paths, stack traces and raw plant data out of responses.
            raise HTTPException(status_code=500, detail="The deterministic ML pipeline could not complete this analysis.") from exc
        if not isinstance(result, dict):
            raise HTTPException(status_code=502, detail="The ML pipeline returned an invalid result.")
        if result.get("analysis_status") not in {"success", "partial", "invalid_input", "failed"}:
            raise HTTPException(status_code=502, detail="The ML pipeline returned an unknown analysis status.")
        return result
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
        ANALYSIS_SLOTS.release()
