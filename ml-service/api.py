"""Private HTTP boundary for the deterministic SolarSleuth ML pipeline.

Run from ml-service/: python -m uvicorn api:app --host 127.0.0.1 --port 8002
The HTTP adapter accepts operating data and optional weather, forecast, device,
and event-log CSV/XLSX context files.
"""
from __future__ import annotations

import asyncio
import hmac
import io
import math
import os
import tempfile
import zipfile
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
MAX_ROWS = int(os.getenv("MAX_ROWS", "1000000"))
MAX_COLUMNS = int(os.getenv("MAX_COLUMNS", "500"))
MAX_XLSX_UNCOMPRESSED_BYTES = int(os.getenv("MAX_XLSX_UNCOMPRESSED_BYTES", str(250 * 1024 * 1024)))

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
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                expanded = sum(item.file_size for item in archive.infolist())
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=415, detail="The XLSX workbook is not a readable ZIP archive.") from exc
        if expanded > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=413, detail="The XLSX workbook expands beyond the allowed size.")
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
        delimiter = max((",", ";", chr(9)), key=header.count)
        if header.count(delimiter) + 1 > MAX_COLUMNS:
            raise HTTPException(status_code=413, detail=f"The CSV has more than {MAX_COLUMNS} columns.")
        if decoded.count("\n") > MAX_ROWS + 1:
            raise HTTPException(status_code=413, detail=f"The CSV has more than {MAX_ROWS:,} data rows.")
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
    weather_file: UploadFile | None = File(None),
    forecast_file: UploadFile | None = File(None),
    devices_file: UploadFile | None = File(None),
    event_log_file: UploadFile | None = File(None),
    plant_id: str = Form("unknown-plant"),
    mode: Literal["auto", "snapshot", "full"] = Form("auto"),
    timezone: str | None = Form(None),
    interval_minutes: float | None = Form(None),
    sheet_name: str | None = Form(None),
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
) -> dict:
    require_service_token(x_service_token)

    if interval_minutes is not None and (not math.isfinite(interval_minutes) or interval_minutes <= 0):
        raise HTTPException(status_code=422, detail="interval_minutes must be a finite number greater than zero.")
    plant_id = plant_id.strip() or "unknown-plant"
    if len(plant_id) > 128 or (timezone is not None and len(timezone) > 64) or (sheet_name is not None and len(sheet_name) > 128):
        raise HTTPException(status_code=422, detail="One or more analysis options exceed the allowed length.")

    uploads = {
        "operating": file,
        "weather": weather_file,
        "forecast": forecast_file,
        "devices": devices_file,
        "event": event_log_file,
    }
    contents: list[tuple[str, bytes]] = []
    total_size = 0
    for role, upload in uploads.items():
        if upload is None:
            continue
        filename = Path((upload.filename or "dataset").replace(chr(92), "/")).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            await upload.close()
            raise HTTPException(status_code=415, detail="All analysis inputs must be CSV or XLSX files.")
        try:
            content = await upload.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await upload.close()
        if not content:
            if role == "operating":
                raise HTTPException(status_code=422, detail="The operating-data file is empty.")
            raise HTTPException(status_code=422, detail=f"The optional {role} file is empty.")
        total_size += len(content)
        if total_size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Combined upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
        validate_upload(filename, content)
        prefix = "event_log" if role == "event" else role
        contents.append((f"{prefix}_{filename}", content))

    try:
        await asyncio.wait_for(ANALYSIS_SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="ML analysis capacity is busy. Retry shortly.") from exc

    try:
        with tempfile.TemporaryDirectory(prefix="solarsleuth-ml-") as temp_dir:
            for filename, content in contents:
                (Path(temp_dir) / filename).write_bytes(content)
            try:
                result = await run_in_threadpool(
                    run_pipeline,
                    temp_dir,
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
                raise HTTPException(status_code=500, detail="The deterministic ML pipeline could not complete this analysis.") from exc
            if not isinstance(result, dict):
                raise HTTPException(status_code=502, detail="The ML pipeline returned an invalid result.")
            if result.get("analysis_status") not in {"success", "partial", "invalid_input", "failed"}:
                raise HTTPException(status_code=502, detail="The ML pipeline returned an unknown analysis status.")
            return result
    finally:
        ANALYSIS_SLOTS.release()
