"""Frontend-facing API and orchestration for SolarSleuth.

Deterministic calculations run only in the ML service. The local LLM receives
the bounded, structured ML result and produces language explanations only.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from uuid import uuid4
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from schemas import AnalyzeRequest, AnalyzeResponse

load_dotenv()

LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8000").rstrip("/")
ML_API_URL = os.getenv("ML_API_URL", "http://127.0.0.1:8002").rstrip("/")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
ML_TIMEOUT_SECONDS = float(os.getenv("ML_TIMEOUT_SECONDS", "300"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",") if x.strip()]


def _service_headers() -> dict[str, str]:
    if INTERNAL_SERVICE_TOKEN:
        return {"X-Service-Token": INTERNAL_SERVICE_TOKEN}
    if ENVIRONMENT == "production":
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
    return {}


def _compact_ml_result(result: dict[str, Any]) -> dict[str, Any]:
    """Bound the LLM context while preserving ML calculations and provenance."""
    return {
        "schema_version": result.get("schema_version"),
        "analysis_status": result.get("analysis_status"),
        "analysis_mode": result.get("analysis_mode"),
        "summary": result.get("summary"),
        "interval": result.get("interval"),
        "energy": result.get("energy"),
        "waterfall": result.get("waterfall"),
        "data_quality": result.get("data_quality"),
        "capabilities": result.get("capabilities"),
        "anomalies": (result.get("anomalies") or [])[:30],
        "hypotheses": (result.get("hypotheses") or [])[:30],
        "evidence": (result.get("evidence") or [])[:40],
        "limitations": (result.get("limitations") or [])[:30],
        "unresolved_fields": (result.get("unresolved_fields") or [])[:40],
        "missing_required_fields": result.get("missing_required_fields"),
        "method": result.get("method"),
        "model_status": result.get("model_status"),
        "errors": result.get("errors"),
        "truncated_for_explanation": (
            len(result.get("anomalies") or []) > 30
            or len(result.get("hypotheses") or []) > 30
            or len(result.get("evidence") or []) > 40
            or len(result.get("limitations") or []) > 30
        ),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Solar Recovery Intelligence Backend",
    version="1.1.0",
    description="Secure orchestration API for deterministic ML analysis and local LLM explanations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


async def forward_to_llm(payload: dict[str, Any]) -> dict[str, Any]:
    timeout = httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            f"{LLM_API_URL}/api/v1/analyze",
            json=payload,
            headers=_service_headers(),
        )
        if response.status_code >= 400:
            if response.status_code in (401, 403):
                raise HTTPException(status_code=503, detail="Local explanation service authentication failed.")
            if response.status_code in (503, 504):
                raise HTTPException(status_code=503, detail="Local explanation service is unavailable.")
            raise HTTPException(status_code=502, detail="Local explanation service could not process the request.")
        try:
            body = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Local explanation service returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=502, detail="Local explanation service returned an invalid response.")
        return body


async def forward_to_ml(
    data: bytes,
    filename: str,
    *,
    plant_id: str,
    mode: str,
    timezone: str | None,
    interval_minutes: float | None,
    sheet_name: str | None,
) -> dict[str, Any]:
    timeout = httpx.Timeout(ML_TIMEOUT_SECONDS, connect=5.0)
    files = {"file": (filename, data, "application/octet-stream")}
    form = {"plant_id": plant_id, "mode": mode}
    if timezone:
        form["timezone"] = timezone
    if interval_minutes is not None:
        form["interval_minutes"] = str(interval_minutes)
    if sheet_name:
        form["sheet_name"] = sheet_name
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.post(
                f"{ML_API_URL}/api/v1/analyze",
                files=files,
                data=form,
                headers=_service_headers(),
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="ML analysis timed out.") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="ML analysis service is unavailable.") from exc
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise HTTPException(status_code=503, detail="ML service authentication failed.")
        if response.status_code in (413, 415, 422):
            raise HTTPException(status_code=response.status_code, detail="ML service rejected the dataset or analysis options.")
        raise HTTPException(status_code=502, detail="ML service could not analyze the dataset.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="ML service returned invalid JSON.") from exc
    if not isinstance(result, dict) or not result.get("schema_version"):
        raise HTTPException(status_code=502, detail="ML service returned an invalid analysis contract.")
    return result


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "solar-recovery-backend"}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ready",
        "service": "solar-recovery-backend",
        "ml_api_reachable": False,
        "llm_api_reachable": False,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), trust_env=False) as client:
        for key, url in (("ml", ML_API_URL), ("llm", LLM_API_URL)):
            try:
                response = await client.get(f"{url}/health")
                response.raise_for_status()
                result[f"{key}_api_reachable"] = True
            except httpx.HTTPError:
                result["status"] = "degraded"
    return result


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Backward-compatible manual-reading path; no calculations are performed here."""
    request_id = request.request_id or str(uuid4())
    payload = request.model_dump()
    payload["request_id"] = request_id
    try:
        raw_result = await forward_to_llm(payload)
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Local explanation request timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Local explanation service is unavailable.") from exc
    raw_result["request_id"] = request_id
    try:
        return AnalyzeResponse.model_validate(raw_result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Local explanation response did not match the expected schema.") from exc


@app.post("/api/v1/analyze/upload", response_model=AnalyzeResponse)
async def analyze_dataset(
    file: UploadFile = File(...),
    plant_id: str = Form(..., min_length=1, max_length=128),
    mode: str = Form("auto"),
    timezone: str | None = Form(None, max_length=64),
    interval_minutes: float | None = Form(None, gt=0, le=1440),
    sheet_name: str | None = Form(None, max_length=128),
) -> AnalyzeResponse:
    """Run deterministic ML analysis first, then ask the local LLM to explain it."""
    request_id = str(uuid4())
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX dataset.")
    if mode not in {"auto", "snapshot", "full"}:
        raise HTTPException(status_code=422, detail="mode must be auto, snapshot, or full.")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded dataset is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Dataset exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")

    # The source file is held in memory only for this request and is never persisted by this API.
    ml_result = await forward_to_ml(
        data,
        f"dataset{suffix}",
        plant_id=plant_id.strip(),
        mode=mode,
        timezone=timezone,
        interval_minutes=interval_minutes,
        sheet_name=sheet_name,
    )
    compact = _compact_ml_result(ml_result)
    llm_payload = {
        "request_id": request_id,
        "plant_id": plant_id.strip(),
        "timestamp": None,
        "plant_context": {"analysis_mode": ml_result.get("analysis_mode"), "interval": ml_result.get("interval", {})},
        "observations": {
            "ml_summary": ml_result.get("summary"),
            "analysis_status": ml_result.get("analysis_status"),
            "data_quality": ml_result.get("data_quality"),
            "energy": ml_result.get("energy"),
            "waterfall": ml_result.get("waterfall"),
            "limitations": (ml_result.get("limitations") or [])[:20],
        },
        "ml_results": compact,
        "retrieved_context": [],
    }
    raw_result = await forward_to_llm(llm_payload)
    raw_result["request_id"] = request_id
    raw_result["plant_id"] = plant_id.strip()
    raw_result["ml_analysis"] = ml_result
    raw_result["analysis_mode"] = ml_result.get("analysis_mode")
    try:
        return AnalyzeResponse.model_validate(raw_result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Combined analysis response did not match the expected schema.") from exc
