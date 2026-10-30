"""Private HTTP adapter for the existing SolarSleuth deterministic ML pipeline.

Run from ML-models/: uvicorn api:app --host 127.0.0.1 --port 8002
The service is intended to be reachable only by the application backend.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from secrets import compare_digest
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from src.pipeline import run_pipeline

MAX_UPLOAD_BYTES = int(os.getenv("ML_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
SERVICE_TOKEN = os.getenv("ML_SERVICE_TOKEN", "")
ALLOWED_SUFFIXES = {".csv", ".xlsx"}

app = FastAPI(
    title="SolarSleuth ML Analysis Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _authorize(token: str | None) -> None:
    # Local development may omit a token; deployments must configure one.
    if SERVICE_TOKEN and (not token or not compare_digest(token, SERVICE_TOKEN)):
        raise HTTPException(status_code=401, detail="Service authentication failed.")
    if not SERVICE_TOKEN and os.getenv("ENVIRONMENT", "development").lower() == "production":
        raise HTTPException(status_code=503, detail="ML_SERVICE_TOKEN must be configured in production.")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "solar-sleuth-ml"}


@app.post("/api/v1/analyze")
async def analyze_upload(
    file: UploadFile = File(...),
    plant_id: str = Form(..., min_length=1, max_length=128),
    mode: str = Form("auto"),
    timezone: str | None = Form(None, max_length=64),
    interval_minutes: float | None = Form(None, gt=0, le=1440),
    sheet_name: str | None = Form(None, max_length=128),
    x_service_token: str | None = Header(None),
) -> dict[str, Any]:
    _authorize(x_service_token)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX dataset.")
    if mode not in {"auto", "snapshot", "full"}:
        raise HTTPException(status_code=422, detail="mode must be auto, snapshot, or full.")

    # Read with a hard cap; never trust Content-Length or the submitted filename.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded dataset is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Dataset exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="solarsleuth-", suffix=suffix, delete=False) as handle:
            temp_path = handle.name
            handle.write(data)
        result = await run_in_threadpool(
            run_pipeline,
            temp_path,
            None,
            mode=mode,
            timezone=timezone,
            interval_minutes=interval_minutes,
            plant_id=plant_id.strip(),
            sheet_name=sheet_name,
        )
        return result
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
        await file.close()
