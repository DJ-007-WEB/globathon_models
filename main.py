"""Application backend for Solar Recovery Intelligence.

This service validates frontend requests and forwards them to the separate local
LLM API. It deliberately does not import or run the teammate's ML implementation.
"""
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import AnalyzeRequest, AnalyzeResponse

load_dotenv()

LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8000").rstrip("/")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep the backend startup independent of the local model's availability.
    # /health remains available even if the LLM service is temporarily offline.
    yield


app = FastAPI(
    title="Solar Recovery Intelligence Backend",
    version="1.0.0",
    description="Frontend-facing API and orchestration layer for solar plant analysis.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


async def forward_to_llm(payload: dict) -> dict:
    """Call the local LLM service and return its JSON response."""
    timeout = httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{LLM_API_URL}/api/v1/analyze", json=payload)
        if response.status_code >= 400:
            detail = "The local LLM service rejected the analysis request."
            try:
                detail = response.json().get("detail", detail)
            except (ValueError, AttributeError):
                pass
            if response.status_code == 422:
                raise HTTPException(status_code=422, detail=f"LLM request validation failed: {detail}")
            if response.status_code in (503, 504):
                raise HTTPException(status_code=503, detail=f"Local LLM service unavailable: {detail}")
            raise HTTPException(status_code=502, detail=f"Local LLM service error: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Local LLM service returned invalid JSON.") from exc


@app.get("/health")
async def health() -> dict:
    """Backend liveness check; does not require the LLM to be online."""
    return {"status": "ok", "service": "solar-recovery-backend"}


@app.get("/ready")
async def ready() -> dict:
    """Report whether the upstream local LLM service is reachable and loaded."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.get(f"{LLM_API_URL}/ready")
            response.raise_for_status()
            upstream = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "degraded",
                "service": "solar-recovery-backend",
                "llm_api_reachable": False,
                "reason": str(exc),
            },
        ) from exc

    model_loaded = bool(upstream.get("model_loaded", False))
    result = {
        "status": "ready" if model_loaded else "not_ready",
        "service": "solar-recovery-backend",
        "llm_api_reachable": True,
        "model_loaded": model_loaded,
    }
    if not model_loaded:
        raise HTTPException(status_code=503, detail=result)
    return result


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Forward plant observations to the local LLM and return a stable envelope."""
    request_id = request.request_id or str(uuid4())
    payload = request.model_dump()
    payload["request_id"] = request_id

    try:
        raw_result = await forward_to_llm(payload)
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="The local LLM request timed out. The first inference may take longer while the model loads.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach the local LLM API at {LLM_API_URL}. Confirm that it is running.",
        ) from exc

    # Reject malformed upstream bodies cleanly rather than leaking a 500 response.
    if not isinstance(raw_result, dict):
        raise HTTPException(status_code=502, detail="Local LLM service returned a JSON value instead of an object.")

    # Normalize the request ID at this boundary and validate the upstream contract.
    raw_result["request_id"] = request_id
    try:
        return AnalyzeResponse.model_validate(raw_result)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local LLM response did not match the expected response schema: {exc}",
        ) from exc
