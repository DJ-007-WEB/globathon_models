"""Frontend-facing orchestration API for SolarSleuth.

Manual requests remain supported at POST /api/v1/analyze.
Dataset uploads run through deterministic ML first, then pass the ML contract
to the local LLM strictly for explanation at POST /api/v1/analyze/upload.
"""
from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from schemas import AnalyzeRequest, AnalyzeResponse

load_dotenv()

ML_API_URL = os.getenv("ML_API_URL", "http://127.0.0.1:8002").rstrip("/")
LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8000").rstrip("/")
ML_TIMEOUT_SECONDS = float(os.getenv("ML_TIMEOUT_SECONDS", "300"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN")
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if x.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="SolarSleuth Application Backend",
    version="2.0.0",
    description="Upload validation, deterministic ML orchestration and local LLM explanation.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _internal_headers() -> dict[str, str]:
    if SERVICE_TOKEN:
        return {"X-Service-Token": SERVICE_TOKEN}
    if ENVIRONMENT == "production":
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
    return {}


async def _post_llm(payload: dict) -> dict:
    timeout = httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                f"{LLM_API_URL}/api/v1/analyze",
                json=payload,
                headers=_internal_headers(),
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="The local LLM request timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Cannot reach the local LLM API. Confirm that it is running.") from exc
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The local LLM rejected internal service authentication.")
        if response.status_code in (503, 504):
            raise HTTPException(status_code=503, detail="The local LLM service is unavailable or not ready.")
        raise HTTPException(status_code=502, detail="The local LLM service rejected or failed the explanation request.")
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="The local LLM returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="The local LLM returned an invalid response object.")
    return value


# Compatibility seam retained for existing manual-input callers and tests.
async def forward_to_llm(payload: dict) -> dict:
    return await _post_llm(payload)


async def _run_ml(
    content: bytes,
    filename: str,
    *,
    plant_id: str,
    mode: str,
    timezone: str | None,
    interval_minutes: float | None,
    sheet_name: str | None,
) -> dict:
    timeout = httpx.Timeout(ML_TIMEOUT_SECONDS, connect=5.0)
    data = {"plant_id": plant_id, "mode": mode}
    if timezone:
        data["timezone"] = timezone
    if interval_minutes is not None:
        data["interval_minutes"] = str(interval_minutes)
    if sheet_name:
        data["sheet_name"] = sheet_name
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                f"{ML_API_URL}/api/v1/analyze",
                data=data,
                files={"file": (filename, content, "application/octet-stream")},
                headers=_internal_headers(),
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="The deterministic ML analysis timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Cannot reach the deterministic ML service on port 8002.") from exc
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The ML service rejected internal service authentication.")
        raise HTTPException(status_code=response.status_code if response.status_code in (413, 415, 422) else 502,
                            detail="The deterministic ML service could not process this dataset.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="The ML service returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="The ML service returned an invalid result object.")
    status = result.get("analysis_status")
    if status in {"invalid_input", "failed"}:
        detail = result.get("summary") or "The uploaded dataset did not pass ML analysis."
        raise HTTPException(status_code=422, detail=detail)
    if status not in {"success", "partial"}:
        raise HTTPException(status_code=502, detail="The ML service returned an unknown analysis status.")
    return result


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-application-backend"}


@app.get("/ready")
async def ready() -> dict:
    checks: dict[str, bool] = {"ml_service_reachable": False, "llm_api_reachable": False, "model_loaded": False}
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), trust_env=False) as client:
        for key, url in (("ml_service_reachable", ML_API_URL), ("llm_api_reachable", LLM_API_URL)):
            try:
                response = await client.get(f"{url}/ready")
                response.raise_for_status()
                data = response.json()
                checks[key] = True
                if key == "llm_api_reachable":
                    checks["model_loaded"] = bool(data.get("model_loaded", False))
            except (httpx.HTTPError, ValueError):
                pass
    is_ready = checks["ml_service_reachable"] and checks["llm_api_reachable"]
    return {"status": "ready" if is_ready else "degraded", "service": "solarsleuth-application-backend", **checks}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Existing manual-input path; no ML calculations are performed here."""
    request_id = request.request_id or str(uuid4())
    payload = request.model_dump()
    payload["request_id"] = request_id
    raw = await forward_to_llm(payload)
    raw["request_id"] = request_id
    raw.setdefault("plant_id", request.plant_id)
    return AnalyzeResponse.model_validate(raw)


@app.post("/api/v1/analyze/upload", response_model=AnalyzeResponse)
async def analyze_upload(
    file: UploadFile = File(...),
    plant_id: str = Form("unknown-plant"),
    mode: str = Form("auto"),
    timezone: str | None = Form(None),
    interval_minutes: float | None = Form(None),
    sheet_name: str | None = Form(None),
) -> AnalyzeResponse:
    """Validate a dataset, run deterministic ML, then ask the LLM to explain it."""
    request_id = str(uuid4())
    filename = file.filename or "dataset"
    if os.path.splitext(filename)[1].lower() not in {".csv", ".xlsx"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Only CSV and XLSX files are supported.")
    if mode not in {"auto", "snapshot", "full"}:
        await file.close()
        raise HTTPException(status_code=422, detail="mode must be auto, snapshot, or full.")
    if interval_minutes is not None and interval_minutes <= 0:
        await file.close()
        raise HTTPException(status_code=422, detail="interval_minutes must be greater than zero.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured 25 MiB limit.")

    ml_result = await _run_ml(
        content, filename, plant_id=plant_id, mode=mode, timezone=timezone,
        interval_minutes=interval_minutes, sheet_name=sheet_name,
    )
    # The full versioned contract is passed as data, not as instructions.
    llm_payload = {
        "request_id": request_id,
        "plant_id": plant_id,
        "timestamp": None,
        "plant_context": {
            "source": "uploaded_dataset",
            "analysis_mode": ml_result.get("analysis_mode"),
            "user_question": "Explain the deterministic ML analysis. Do not recalculate its metrics.",
        },
        "observations": {
            "analysis_status": ml_result.get("analysis_status"),
            "summary": ml_result.get("summary"),
            "interval": ml_result.get("interval", {}),
            "data_quality": ml_result.get("data_quality", {}),
            "limitations": ml_result.get("limitations", []),
            "unresolved_fields": ml_result.get("unresolved_fields", []),
        },
        "ml_results": ml_result,
        "retrieved_context": [],
    }
    explanation = await _post_llm(llm_payload)
    explanation["request_id"] = request_id
    explanation["plant_id"] = plant_id
    explanation["ml_analysis"] = ml_result
    explanation["analysis_mode"] = ml_result.get("analysis_mode")
    return AnalyzeResponse.model_validate(explanation)
