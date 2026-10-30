"""FastAPI entry point for the local SolarSleuth explanation-only LLM service."""
import hmac
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from llm_service import LLMService
from schemas import AnalysisRequest, AnalysisResponse, AnalyzeResponse

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-0.8B")
ADAPTER_PATH = os.getenv("ADAPTER_PATH", "models/solar-qwen-lora-final")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN")
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if x.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep model loading lazy; LLMService loads on the first inference request.
    app.state.llm_service = LLMService(model_name=MODEL_NAME, adapter_path=ADAPTER_PATH)
    yield


app = FastAPI(title="SolarSleuth Local Explanation API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Service-Token"],
)


def require_service_token(token: str | None) -> None:
    if not SERVICE_TOKEN:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Internal service authentication is not configured.")
        return
    if not token or not hmac.compare_digest(token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal service credentials.")


@app.get("/health")
def health():
    return {"status": "ok", "service": "solarsleuth-local-llm"}


@app.get("/ready")
def ready():
    service = getattr(app.state, "llm_service", None)
    loaded = bool(service and service.is_loaded)
    return {"status": "ready" if loaded else "not_loaded", "model_loaded": loaded}


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
        raise HTTPException(status_code=503, detail="Configured local model or adapter files were not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Model returned an invalid explanation: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Local model inference failed.") from exc
    return AnalyzeResponse(
        request_id=request.request_id,
        plant_id=request.plant_id,
        analysis=analysis,
        model=MODEL_NAME,
    )
