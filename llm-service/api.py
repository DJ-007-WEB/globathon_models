"""Private FastAPI boundary for SolarSleuth's local explanation-only LLM."""
from __future__ import annotations

import hmac
import os
import threading
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
MAX_NEW_TOKENS = max(128, min(int(os.getenv("MAX_NEW_TOKENS", "700")), 1024))
# Prompt budget; raise only if the model's context window and hardware allow it.
MAX_INPUT_TOKENS = max(2048, min(int(os.getenv("MAX_INPUT_TOKENS", "7600")), 32768))
# auto = fine-tuned adapter first, base model fallback; "adapter" or "base" pins one path.
ADAPTER_MODE = os.getenv("LLM_ADAPTER_MODE", "auto").strip().lower()
# Stop starting new generation attempts after this many seconds (backend waits LLM_TIMEOUT_SECONDS).
TIME_BUDGET_SECONDS = float(os.getenv("LLM_TIME_BUDGET_SECONDS", "240"))


# Load the model in the background at startup (default on) so the first upload does not
# wait for it and /ready reports the real state. Set LLM_WARMUP_ON_STARTUP=false to disable.
WARMUP_ON_STARTUP = os.getenv("LLM_WARMUP_ON_STARTUP", "true").strip().lower() in {"1", "true", "yes", "on"}


def _background_load(service: LLMService) -> None:
    service.loading = True
    try:
        service._load()
    except Exception as exc:  # surfaced through /ready, never crashes the service
        service.last_load_error = f"Model load failed: {type(exc).__name__}: {exc}"[:400]
    finally:
        service.loading = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENVIRONMENT == "production" and not SERVICE_TOKEN:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must be configured in production.")
    app.state.llm_service = LLMService(
        model_name=MODEL_NAME,
        adapter_path=ADAPTER_PATH,
        max_new_tokens=MAX_NEW_TOKENS,
        max_input_tokens=MAX_INPUT_TOKENS,
        adapter_mode=ADAPTER_MODE,
        time_budget_seconds=TIME_BUDGET_SECONDS,
    )
    app.state.llm_service.loading = False
    if ENVIRONMENT == "production":
        # Production waits for the model before serving traffic.
        try:
            await run_in_threadpool(app.state.llm_service._load)
        except Exception:
            app.state.llm_service.last_load_error = (
                "Startup warmup failed. Check the configured base model and complete PEFT adapter."
            )
    elif WARMUP_ON_STARTUP:
        threading.Thread(target=_background_load, args=(app.state.llm_service,), daemon=True).start()
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
    inference_error = service.last_inference_error if service else None
    return {
        "status": "ready" if loaded and not inference_error else (
            "loading" if service and getattr(service, "loading", False)
            else "not_ready" if service and (service.last_load_error or inference_error) else "not_loaded"),
        "service": "solarsleuth-local-llm",
        "model_loaded": loaded,
        "adapter_available": adapter_exists,
        "model_name": service.resolved_model_name if service else MODEL_NAME,
        "load_error": service.last_load_error if service else None,
        "last_inference_error": inference_error,
        "last_prompt_tokens": service.last_prompt_tokens if service else None,
        "last_generation_path": getattr(service, "last_generation_path", None) if service else None,
    }


@app.post("/warmup")
async def warmup() -> dict:
    """Load the configured base model and adapter before a demo or first request."""
    service: LLMService = app.state.llm_service
    try:
        await run_in_threadpool(service._load)
    except Exception as exc:
        service.last_load_error = "Configured model or LoRA adapter could not be loaded."
        raise HTTPException(status_code=503, detail="Local model warmup failed. Check the configured model and adapter.") from exc
    service.last_load_error = None
    return {
        "status": "ready",
        "model_loaded": service.is_loaded,
        "model_name": service.resolved_model_name or MODEL_NAME or "adapter-configured-model",
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
        service.last_inference_error = "Model or adapter files are unavailable."
        raise HTTPException(
            status_code=503,
            detail="Configured local model or LoRA adapter files are unavailable. Check ADAPTER_PATH and adapter metadata.",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        if not service.last_inference_error:
            service.last_inference_error = f"Inference failed: {type(exc).__name__}: {exc}"
        raise HTTPException(status_code=503, detail="Local model inference could not produce a valid explanation.") from exc
    service.last_inference_error = None
    return AnalyzeResponse(
        request_id=request.request_id,
        plant_id=request.plant_id,
        analysis=analysis,
        model=service.resolved_model_name or MODEL_NAME or "adapter-configured-model",
    )