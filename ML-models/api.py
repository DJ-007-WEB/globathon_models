"""Private HTTP boundary for the deterministic SolarSleuth ML pipeline.

Run from ML-models/: python -m uvicorn api:app --host 127.0.0.1 --port 8002
The API accepts one operating-data CSV/XLSX file per request. Multi-file
weather/device/forecast/event-log ingestion remains available in the Python
pipeline but is not yet exposed by this single-file HTTP endpoint.
"""
from __future__ import annotations

import hmac
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from src.pipeline import run_pipeline

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN") or os.getenv("ML_SERVICE_TOKEN")

app = FastAPI(
    title="SolarSleuth Deterministic ML API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)


def require_service_token(token: str | None) -> None:
    if not SERVICE_TOKEN:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
        return
    if not token or not hmac.compare_digest(token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal service credentials.")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-deterministic-ml"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready", "service": "solarsleuth-deterministic-ml", "pipeline_available": True}


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
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Only CSV and XLSX operating-data files are supported.")
    if interval_minutes is not None and interval_minutes <= 0:
        raise HTTPException(status_code=422, detail="interval_minutes must be greater than zero.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(content)
            temp_path = handle.name
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
        if not isinstance(result, dict):
            raise HTTPException(status_code=502, detail="The ML pipeline returned an invalid result.")
        return result
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
