"""Browser-facing API and ML-first orchestration for SolarSleuth.

The backend is the only browser-facing service. It validates an upload,
invokes deterministic ML, then forwards bounded ML evidence to the local LLM.
It never calculates or changes plant metrics.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from schemas import AnalyzeResponse

load_dotenv()

ML_API_URL = os.getenv("ML_API_URL", "http://127.0.0.1:8002").rstrip("/")
LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8000").rstrip("/")
ML_TIMEOUT_SECONDS = float(os.getenv("ML_TIMEOUT_SECONDS", "300"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CONCURRENT_ANALYSES = int(os.getenv("MAX_CONCURRENT_ANALYSES", "2"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN")
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN")
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if x.strip()]
ANALYSIS_SLOTS = asyncio.Semaphore(max(1, MAX_CONCURRENT_ANALYSES))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENVIRONMENT == "production" and not API_ACCESS_TOKEN:
        raise RuntimeError("API_ACCESS_TOKEN must be configured in production.")
    if ENVIRONMENT == "production" and not SERVICE_TOKEN:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must be configured in production.")
    yield


app = FastAPI(
    title="SolarSleuth Application Backend",
    version="2.1.0",
    description="File upload validation, deterministic ML orchestration and local LLM explanation.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _authorize_browser(authorization: str | None) -> None:
    """Optional local-dev access; production requires a deployment access token.

    This is a deployment gate, not multi-user identity or role-based access control.
    """
    if not API_ACCESS_TOKEN:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Browser API access is not configured.")
        return
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(supplied, API_ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Authentication required.")


def _internal_headers() -> dict[str, str]:
    if SERVICE_TOKEN:
        return {"X-Service-Token": SERVICE_TOKEN}
    if ENVIRONMENT == "production":
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
    return {}


def _safe_filename(filename: str | None) -> str:
    raw = Path((filename or "dataset").replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._")
    if not cleaned or len(cleaned) > 160:
        raise HTTPException(status_code=422, detail="The uploaded filename is invalid.")
    return cleaned


def _validate_file_signature(filename: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        if not content.startswith(b"PK\\x03\\x04"):
            raise HTTPException(status_code=415, detail="The file extension is XLSX but its content is not a valid XLSX/ZIP signature.")
        return
    if suffix == ".csv":
        if content.startswith((b"PK\\x03\\x04", b"\\xd0\\xcf\\x11\\xe0")):
            raise HTTPException(status_code=415, detail="The CSV extension does not match the uploaded file content.")
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="CSV files must use UTF-8 encoding.") from exc
        first_line = next((line for line in decoded.splitlines() if line.strip()), "")
        if not first_line or not any(delimiter in first_line for delimiter in (",", ";", "\\t")):
            raise HTTPException(status_code=422, detail="The CSV must contain a delimited header row.")
        return
    raise HTTPException(status_code=415, detail="Only CSV and XLSX files are supported.")


def _compact_ml_for_llm(result: dict) -> dict:
    """Bound the prompt; preserve the full, unchanged ML result for the UI."""
    compact = {
        key: result[key]
        for key in (
            "schema_version", "analysis_status", "analysis_mode", "summary", "request",
            "interval", "energy", "forecast_energy", "expected_energy", "actual_energy",
            "deviation", "waterfall", "data_quality", "capabilities", "units",
            "model_version", "mapping_version", "config_version", "vocab_version",
            "method", "model_status",
        )
        if key in result
    }
    for key, limit in (
        ("anomalies", 12), ("hypotheses", 12), ("evidence", 30),
        ("limitations", 30), ("unresolved_fields", 30),
        ("missing_required_fields", 30), ("errors", 10),
    ):
        value = result.get(key)
        if isinstance(value, list):
            compact[key] = value[:limit]
    quality = compact.get("data_quality")
    if isinstance(quality, dict) and isinstance(quality.get("checks"), list):
        quality = dict(quality)
        quality["checks"] = quality["checks"][:30]
        compact["data_quality"] = quality
    return compact


async def _request_service(method: str, url: str, *, timeout_seconds: float, **kwargs) -> httpx.Response:
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.request(method, url, headers=_internal_headers(), **kwargs)
            return response
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="A dependent analysis service timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="A required local analysis service is unavailable.") from exc


async def _run_ml(content: bytes, filename: str, *, plant_id: str, mode: str,
                  timezone: str | None, interval_minutes: float | None,
                  sheet_name: str | None) -> dict:
    data = {"plant_id": plant_id, "mode": mode}
    if timezone:
        data["timezone"] = timezone
    if interval_minutes is not None:
        data["interval_minutes"] = str(interval_minutes)
    if sheet_name:
        data["sheet_name"] = sheet_name
    response = await _request_service(
        "POST", f"{ML_API_URL}/api/v1/analyze",
        timeout_seconds=ML_TIMEOUT_SECONDS,
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
    )
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The ML service rejected internal service authentication.")
        if response.status_code in (413, 415, 422):
            raise HTTPException(status_code=response.status_code, detail="The deterministic ML service rejected this dataset.")
        raise HTTPException(status_code=502, detail="The deterministic ML service could not process this dataset.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="The ML service returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="The ML service returned an invalid result object.")
    status = result.get("analysis_status")
    if status in {"invalid_input", "failed"}:
        raise HTTPException(status_code=422, detail="The uploaded dataset did not pass deterministic ML validation.")
    if status not in {"success", "partial"}:
        raise HTTPException(status_code=502, detail="The ML service returned an unknown analysis status.")
    return result


async def _post_llm(payload: dict) -> dict:
    response = await _request_service(
        "POST", f"{LLM_API_URL}/api/v1/analyze",
        timeout_seconds=LLM_TIMEOUT_SECONDS,
        json=payload,
    )
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The local LLM rejected internal service authentication.")
        if response.status_code in (503, 504):
            raise HTTPException(status_code=503, detail="The local LLM service is unavailable or not ready.")
        raise HTTPException(status_code=502, detail="The local LLM could not produce an explanation.")
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="The local LLM returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="The local LLM returned an invalid response object.")
    return value


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-application-backend"}


@app.get("/ready")
async def ready() -> dict:
    checks = {"ml_service_reachable": False, "llm_api_reachable": False, "model_loaded": False}
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), trust_env=False) as client:
        for key, url in (("ml_service_reachable", ML_API_URL), ("llm_api_reachable", LLM_API_URL)):
            try:
                response = await client.get(f"{url}/ready")
                response.raise_for_status()
                data = response.json()
                checks[key] = data.get("status") in {"ready", "not_loaded"}
                if key == "llm_api_reachable":
                    checks["model_loaded"] = bool(data.get("model_loaded", False))
            except (httpx.HTTPError, ValueError):
                pass
    is_ready = checks["ml_service_reachable"] and checks["llm_api_reachable"]
    return {"status": "ready" if is_ready else "degraded",
            "service": "solarsleuth-application-backend", **checks}


@app.post("/api/v1/analyze/upload", response_model=AnalyzeResponse)
async def analyze_upload(
    file: UploadFile = File(...),
    plant_id: str = Form("unknown-plant"),
    mode: str = Form("auto"),
    timezone: str | None = Form(None),
    interval_minutes: float | None = Form(None),
    sheet_name: str | None = Form(None),
    authorization: str | None = Header(None, alias="Authorization"),
) -> AnalyzeResponse:
    _authorize_browser(authorization)
    request_id = str(uuid4())
    filename = _safe_filename(file.filename)
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Only CSV and XLSX files are supported.")
    if mode not in {"auto", "snapshot", "full"}:
        await file.close()
        raise HTTPException(status_code=422, detail="mode must be auto, snapshot, or full.")
    if interval_minutes is not None and interval_minutes <= 0:
        await file.close()
        raise HTTPException(status_code=422, detail="interval_minutes must be greater than zero.")
    plant_id = plant_id.strip() or "unknown-plant"
    if len(plant_id) > 128:
        await file.close()
        raise HTTPException(status_code=422, detail="plant_id must be at most 128 characters.")
    if timezone and len(timezone) > 64:
        await file.close()
        raise HTTPException(status_code=422, detail="timezone must be at most 64 characters.")
    if sheet_name and len(sheet_name) > 128:
        await file.close()
        raise HTTPException(status_code=422, detail="sheet_name must be at most 128 characters.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")
    _validate_file_signature(filename, content)

    try:
        await asyncio.wait_for(ANALYSIS_SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="Analysis capacity is busy. Retry shortly.") from exc
    try:
        ml_result = await _run_ml(
            content, filename, plant_id=plant_id, mode=mode, timezone=timezone,
            interval_minutes=interval_minutes, sheet_name=sheet_name,
        )
        llm_payload = {
            "request_id": request_id,
            "plant_id": plant_id,
            "timestamp": None,
            "plant_context": {
                "source": "uploaded_dataset",
                "analysis_mode": ml_result.get("analysis_mode"),
                "user_question": "Explain the deterministic ML analysis. Do not recalculate or change its metrics.",
            },
            "observations": {
                "analysis_status": ml_result.get("analysis_status"),
                "summary": ml_result.get("summary"),
                "interval": ml_result.get("interval", {}),
                "data_quality": ml_result.get("data_quality", {}),
                "limitations": ml_result.get("limitations", []),
                "unresolved_fields": ml_result.get("unresolved_fields", []),
            },
            "ml_results": _compact_ml_for_llm(ml_result),
            "retrieved_context": [],
        }
        try:
            explanation = await _post_llm(llm_payload)
            validated = AnalyzeResponse.model_validate({
                **explanation,
                "request_id": request_id,
                "plant_id": plant_id,
                "ml_analysis": ml_result,
                "analysis_mode": ml_result.get("analysis_mode"),
            })
            return validated
        except HTTPException as exc:
            # Preserve a valid deterministic result if only explanation fails.
            if exc.status_code not in {502, 503, 504}:
                raise
            return AnalyzeResponse(
                request_id=request_id,
                plant_id=plant_id,
                model="unavailable",
                analysis={
                    "summary": "Deterministic analysis completed, but the local AI explanation is unavailable.",
                    "observations": [],
                    "possible_causes": [],
                    "supporting_evidence": [],
                    "recommended_checks": [],
                    "limitations": ["The LLM service did not return a validated explanation. Review the ML analysis below."],
                    "confidence": "insufficient_evidence",
                },
                ml_analysis=ml_result,
                analysis_mode=ml_result.get("analysis_mode"),
            )
        except Exception as exc:
            # Do not leak upstream exception text or discard successful ML facts.
            raise HTTPException(status_code=502, detail="The local LLM returned an invalid explanation response.") from exc
    finally:
        ANALYSIS_SLOTS.release()
