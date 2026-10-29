"""FastAPI entry point for the Solar Recovery Intelligence local LLM service."""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from llm_service import LLMService
from schemas import AnalysisRequest, AnalysisResponse, AnalyzeResponse

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-0.8B")
ADAPTER_PATH = os.getenv("ADAPTER_PATH", "models/solar-qwen-lora-final")
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",") if x.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm_service = LLMService(model_name=MODEL_NAME, adapter_path=ADAPTER_PATH)
    yield


app = FastAPI(title="Solar Recovery Intelligence API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "solar-recovery-llm-api"}


@app.get("/ready")
def ready():
    service = getattr(app.state, "llm_service", None)
    loaded = bool(service and service.is_loaded)
    return {"status": "ready" if loaded else "not_loaded", "model_loaded": loaded}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalysisRequest) -> AnalyzeResponse:
    service: LLMService = app.state.llm_service
    try:
        analysis: AnalysisResponse = await run_in_threadpool(service.analyze, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Model returned an invalid analysis: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Local model inference failed: {exc}") from exc
    return AnalyzeResponse(request_id=request.request_id, plant_id=request.plant_id,
                           analysis=analysis, model=MODEL_NAME)
