"""Private FastAPI boundary for SolarSleuth's local explanation-only LLM."""
from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from llm_service import LLMService
from schemas import AnalysisRequest, AnalysisResponse, AnalyzeResponse

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip() or None
ADAPTER_PATH = os.getenv("ADAPTER_PATH", "models/solar-qwen-lora-final")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN")
MAX_NEW_TOKENS = max(128, min(int(os.getenv("MAX_NEW_TOKENS", "450")), 1024))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENVIRONMENT == "production" and not SERVICE_TOKEN:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must be configured in production.")
    app.state.llm_service = LLMService(
        model_name=MODEL_NAME,
        adapter_path=ADAPTER_PATH,
        max_new_tokens=MAX_NEW_TOKENS,
    )
    yield


app = FastAPI(
    title="SolarSleuth Local Explanation API",
    version="2.1.0",
    description="Private explanation-only service. Numerical authority remains in deterministic ML.",
    lifespan=lifespan,
)


def require_service_token(token: str | None) -> None:
    if not SERVICE_TOKEN:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
        return
    if not token or not hmac.compare_digest(token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal service credentials.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-local-llm"}


@app.get("/ready")
def ready() -> dict:
    service: LLMService | None = getattr(app.state, "llm_service", None)
    loaded = bool(service and service.is_loaded)
    adapter_exists = bool(service and service.adapter_path.is_dir()
                           and (service.adapter_path / "adapter_config.json").is_file())
    return {
        "status": "ready" if loaded else ("not_ready" if service and service.last_load_error else "not_loaded"),
        "service": "solarsleuth-local-llm",
        "model_loaded": loaded,
        "adapter_available": adapter_exists,
        "model_name": service.resolved_model_name if service else MODEL_NAME,
        "load_error": service.last_load_error if service else None,
    }


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalysisRequest,
    x_service_token: str | None = Header(None, alias="X-Service-Token"),
) -> AnalyzeResponse:
    require_service_token(x_service_token)
    service: LLMService = app.state.llm_service
    try:
        analysis: AnalysisResponse = await run_in_threadpool(service.analyze, request)
    except FileNotFoundError as exc:
        service.last_load_error = "Configured model or LoRA adapter could not be loaded."
        raise HTTPException(
            status_code=503,
            detail="Configured local model or LoRA adapter files are unavailable. Check ADAPTER_PATH and adapter metadata.",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        service.last_load_error = "Configured model or LoRA adapter could not be loaded."
        raise HTTPException(status_code=503, detail="Local model inference could not produce a valid explanation.") from exc
    return AnalyzeResponse(
        request_id=request.request_id,
        plant_id=request.plant_id,
        analysis=analysis,
        model=service.resolved_model_name or MODEL_NAME or "adapter-configured-model",
    )
