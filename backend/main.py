"""Browser-facing API and ML-first orchestration for SolarSleuth.

The backend is the only browser-facing service. It validates an upload,
invokes deterministic ML, then forwards bounded ML evidence to the local LLM.
It never calculates or changes plant metrics.
"""
from __future__ import annotations

import asyncio
import hmac
import math
import os
import re
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.concurrency import run_in_threadpool

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json

from schemas import AnalyzeResponse

load_dotenv()

ML_API_URL = os.getenv("ML_API_URL", "http://127.0.0.1:8002").rstrip("/")
LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8000").rstrip("/")
ML_TIMEOUT_SECONDS = float(os.getenv("ML_TIMEOUT_SECONDS", "300"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CONCURRENT_ANALYSES = int(os.getenv("MAX_CONCURRENT_ANALYSES", "2"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN")
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "solarsleuth")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))
password_hasher = PasswordHash.recommended()
mongo_client: MongoClient | None = None
database = None
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if x.strip()]
ANALYSIS_SLOTS = asyncio.Semaphore(max(1, MAX_CONCURRENT_ANALYSES))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, database
    if ENVIRONMENT == "production" and not MONGODB_URI:
        raise RuntimeError("MONGODB_URI must be configured in production.")
    if ENVIRONMENT == "production" and (len(JWT_SECRET) < 32 or JWT_SECRET == "replace-with-a-long-random-secret"):
        raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters.")
    if MONGODB_URI:
        try:
            mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
            mongo_client.admin.command("ping")
            database = mongo_client[MONGODB_DATABASE]
            await run_in_threadpool(database.users.create_index, "email", unique=True)
            await run_in_threadpool(database.plants.create_index, [("business_id", 1), ("plant_id", 1)], unique=True)
            await run_in_threadpool(database.plants.create_index, [("business_id", 1), ("created_at", -1)])
            await run_in_threadpool(database.analyses.create_index, [("business_id", 1), ("created_at", -1)])
            await run_in_threadpool(database.analyses.create_index, [("business_id", 1), ("plant_id", 1), ("created_at", -1)])
            await run_in_threadpool(database.analyses.create_index, [("business_id", 1), ("request_id", 1)], unique=True)
            await run_in_threadpool(database.analysis_messages.create_index, [("business_id", 1), ("request_id", 1), ("created_at", 1)])
        except PyMongoError as exc:
            if ENVIRONMENT == "production":
                raise RuntimeError("MongoDB connection failed. Check MONGODB_URI and network access.") from exc
            mongo_client = None
            database = None
    if ENVIRONMENT == "production" and not SERVICE_TOKEN:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must be configured in production.")
    yield
    if mongo_client is not None:
        mongo_client.close()


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


def _database_required():
    if database is None:
        raise HTTPException(status_code=503, detail="Account storage is not configured. Set MONGODB_URI in services/backend/.env.")
    return database


def _issue_access_token(user: dict) -> str:
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured. Set a random secret of at least 32 characters.")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user["user_id"], "business_id": user["business_id"],
         "email": user["email"], "iat": now,
         "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def _authorize_browser(authorization: str | None) -> dict:
    """Validate a signed account token; legacy static token remains an optional deployment gate."""
    if API_ACCESS_TOKEN:
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if authorization and authorization.startswith("Bearer ") and hmac.compare_digest(supplied, API_ACCESS_TOKEN):
            return {"user_id": "legacy-deployment-user", "business_id": "legacy-deployment-workspace"}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to access this workspace.")
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Account authentication is not configured.")
    try:
        claims = jwt.decode(authorization[7:].strip(), JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not claims.get("sub") or not claims.get("business_id"):
            raise ValueError("Required claims missing")
        return {"user_id": claims["sub"], "business_id": claims["business_id"], "email": claims.get("email", "")}
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Your session is invalid or expired. Please sign in again.")


def _public_user(user: dict) -> dict:
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"],
            "business_id": user["business_id"], "business_name": user["business_name"]}


from pydantic import BaseModel


class AuthPayload(BaseModel):
    email: str
    password: str


class RegisterPayload(AuthPayload):
    name: str
    business_name: str


class AnalysisChatPayload(BaseModel):
    question: str


class PlantPayload(BaseModel):
    plant_id: str
    name: str
    location: str | None = None
    capacity_kw: float | None = None
    timezone: str | None = None


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
            "interval", "energy", "device_performance", "forecast_energy", "expected_energy", "actual_energy",
            "deviation", "waterfall", "data_quality", "capabilities", "units",
            "model_version", "mapping_version", "config_version", "vocab_version",
            "method", "model_status",
        )
        if key in result
    }
    for key, limit in (
        ("device_performance", 20), ("anomalies", 12), ("hypotheses", 12), ("evidence", 30),
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
                  sheet_name: str | None,
                  context_files: dict[str, tuple[str, bytes]] | None = None) -> dict:
    data = {"plant_id": plant_id, "mode": mode}
    if timezone:
        data["timezone"] = timezone
    if interval_minutes is not None:
        data["interval_minutes"] = str(interval_minutes)
    if sheet_name:
        data["sheet_name"] = sheet_name
    files = {"file": (filename, content, "application/octet-stream")}
    for field, (context_name, context_content) in (context_files or {}).items():
        files[field] = (context_name, context_content, "application/octet-stream")
    response = await _request_service(
        "POST", f"{ML_API_URL}/api/v1/analyze",
        timeout_seconds=ML_TIMEOUT_SECONDS,
        data=data,
        files=files,
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
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
        detail = str(first_error.get("message") or "The uploaded dataset did not pass deterministic ML validation.")
        field = first_error.get("field")
        if field:
            detail += f" (field: {field})"
        raise HTTPException(status_code=422, detail=detail)
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

@app.post("/api/v1/auth/register")
async def register_account(payload: RegisterPayload) -> dict:
    db = _database_required()
    email = payload.email.strip().lower()
    name = payload.name.strip()
    business_name = payload.business_name.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if len(name) < 2 or len(name) > 100:
        raise HTTPException(status_code=422, detail="Name must contain 2 to 100 characters.")
    if len(business_name) < 2 or len(business_name) > 120:
        raise HTTPException(status_code=422, detail="Business name must contain 2 to 120 characters.")
    if len(payload.password) < 10 or len(payload.password) > 128:
        raise HTTPException(status_code=422, detail="Password must contain 10 to 128 characters.")
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured. Set a random secret of at least 32 characters.")
    user = {"user_id": str(uuid4()), "business_id": str(uuid4()), "name": name,
            "email": email, "business_name": business_name,
            "password_hash": password_hasher.hash(payload.password),
            "created_at": datetime.now(timezone.utc)}
    try:
        await run_in_threadpool(db.users.insert_one, user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Account storage is temporarily unavailable.")
    return {"access_token": _issue_access_token(user), "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_MINUTES * 60, "user": _public_user(user)}


@app.post("/api/v1/auth/login")
async def login_account(payload: AuthPayload) -> dict:
    db = _database_required()
    email = payload.email.strip().lower()
    try:
        user = await run_in_threadpool(db.users.find_one, {"email": email})
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Account storage is temporarily unavailable.")
    if not user or not password_hasher.verify(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return {"access_token": _issue_access_token(user), "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_MINUTES * 60, "user": _public_user(user)}


@app.get("/api/v1/auth/me")
async def current_account(authorization: str | None = Header(None, alias="Authorization")) -> dict:
    claims = _authorize_browser(authorization)
    if claims["user_id"] == "legacy-deployment-user":
        return {"user_id": claims["user_id"], "business_id": claims["business_id"],
                "name": "Deployment user", "email": "", "business_name": "Legacy workspace"}
    db = _database_required()
    user = await run_in_threadpool(db.users.find_one, {"user_id": claims["user_id"], "business_id": claims["business_id"]})
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return _public_user(user)




def _public_plant(document: dict) -> dict:
    return {key: document.get(key) for key in (
        "plant_id", "name", "location", "capacity_kw", "timezone", "created_at", "updated_at"
    ) if key in document} | {
        "created_at": document["created_at"].isoformat() if isinstance(document.get("created_at"), datetime) else document.get("created_at"),
        "updated_at": document["updated_at"].isoformat() if isinstance(document.get("updated_at"), datetime) else document.get("updated_at"),
    }


@app.get("/api/v1/plants")
async def list_plants(authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    db = _database_required()
    query = {"business_id": account["business_id"]}
    try:
        cursor = await run_in_threadpool(lambda: db.plants.find(query, {"_id": 0}).sort("created_at", -1).limit(200))
        items = await run_in_threadpool(lambda: list(cursor))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Plant directory is temporarily unavailable.") from exc
    return {"items": [_public_plant(item) for item in items]}


@app.post("/api/v1/plants")
async def create_plant(payload: PlantPayload,
                       authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    plant_id, name = payload.plant_id.strip(), payload.name.strip()
    location = payload.location.strip() if payload.location else None
    timezone_name = payload.timezone.strip() if payload.timezone else None
    if not plant_id or len(plant_id) > 128:
        raise HTTPException(status_code=422, detail="Plant identifier must contain 1 to 128 characters.")
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(status_code=422, detail="Plant name must contain 2 to 120 characters.")
    if location and len(location) > 200:
        raise HTTPException(status_code=422, detail="Location must be at most 200 characters.")
    if timezone_name and len(timezone_name) > 64:
        raise HTTPException(status_code=422, detail="Timezone must be at most 64 characters.")
    if payload.capacity_kw is not None and (not math.isfinite(payload.capacity_kw) or payload.capacity_kw <= 0 or payload.capacity_kw > 1_000_000):
        raise HTTPException(status_code=422, detail="Capacity must be greater than zero and at most 1,000,000 kW.")
    db = _database_required()
    now = datetime.now(timezone.utc)
    document = {"business_id": account["business_id"], "created_by": account["user_id"],
                "plant_id": plant_id, "name": name, "location": location,
                "capacity_kw": payload.capacity_kw, "timezone": timezone_name,
                "created_at": now, "updated_at": now}
    try:
        await run_in_threadpool(db.plants.insert_one, document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A plant with this identifier already exists in this workspace.")
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Plant could not be saved. Check database connectivity.") from exc
    return _public_plant(document)


@app.patch("/api/v1/plants/{plant_id}")
async def update_plant(plant_id: str, payload: PlantPayload,
                      authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    if payload.plant_id.strip() != plant_id:
        raise HTTPException(status_code=422, detail="Plant identifier cannot be changed.")
    name = payload.name.strip()
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(status_code=422, detail="Plant name must contain 2 to 120 characters.")
    location = payload.location.strip() if payload.location else None
    timezone_name = payload.timezone.strip() if payload.timezone else None
    if location and len(location) > 200:
        raise HTTPException(status_code=422, detail="Location must be at most 200 characters.")
    if timezone_name and len(timezone_name) > 64:
        raise HTTPException(status_code=422, detail="Timezone must be at most 64 characters.")
    if payload.capacity_kw is not None and (not math.isfinite(payload.capacity_kw) or payload.capacity_kw <= 0 or payload.capacity_kw > 1_000_000):
        raise HTTPException(status_code=422, detail="Capacity must be finite, greater than zero and at most 1,000,000 kW.")
    db = _database_required()
    query = {"business_id": account["business_id"], "plant_id": plant_id}
    update = {"name": name, "location": location,
              "capacity_kw": payload.capacity_kw, "timezone": timezone_name,
              "updated_at": datetime.now(timezone.utc)}
    try:
        result = await run_in_threadpool(db.plants.update_one, query, {"$set": update})
        if not result.matched_count:
            raise HTTPException(status_code=404, detail="Plant was not found in this business workspace.")
        document = await run_in_threadpool(db.plants.find_one, query, {"_id": 0})
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Plant could not be updated.") from exc
    return _public_plant(document)


def _analysis_document(account: dict, filename: str, plant_id: str, result: AnalyzeResponse) -> dict:
    """Build a metadata-only record; uploaded file bytes are never persisted."""
    return {"request_id": result.request_id, "user_id": account["user_id"],
            "business_id": account["business_id"], "plant_id": plant_id,
            "filename": filename, "analysis_status": (result.ml_analysis or {}).get("analysis_status", "unknown"),
            "analysis_mode": result.analysis_mode, "created_at": datetime.now(timezone.utc),
            "result": result.model_dump(mode="json")}


async def _persist_analysis(account: dict, filename: str, plant_id: str, result: AnalyzeResponse) -> None:
    if database is None:
        if account.get("user_id") == "legacy-deployment-user":
            return
        _database_required()
    try:
        await run_in_threadpool(database.analyses.insert_one, _analysis_document(account, filename, plant_id, result))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Analysis completed but could not be saved. Check database connectivity and retry.") from exc


def _public_analysis_summary(document: dict) -> dict:
    created = document.get("created_at")
    return {"request_id": document["request_id"], "plant_id": document.get("plant_id", "unknown-plant"),
            "filename": document.get("filename", "dataset"), "analysis_status": document.get("analysis_status", "unknown"),
            "analysis_mode": document.get("analysis_mode"),
            "created_at": created.isoformat() if isinstance(created, datetime) else created}


@app.get("/api/v1/analyses")
async def list_analyses(limit: int = 20, offset: int = 0, plant_id: str | None = None,
                        authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1–100 and offset must be non-negative.")
    query = {"business_id": account["business_id"]}
    if plant_id is not None:
        plant_id = plant_id.strip()
        if not plant_id or len(plant_id) > 128:
            raise HTTPException(status_code=422, detail="plant_id must contain 1 to 128 characters.")
        query["plant_id"] = plant_id
    db = _database_required()
    try:
        cursor = await run_in_threadpool(lambda: db.analyses.find(query, {"_id": 0, "result": 0}).sort("created_at", -1).skip(offset).limit(limit))
        items = await run_in_threadpool(lambda: list(cursor))
        total = await run_in_threadpool(db.analyses.count_documents, query)
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Analysis history is temporarily unavailable.") from exc
    return {"items": [_public_analysis_summary(item) for item in items], "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/analyses/{request_id}")
async def get_analysis(request_id: str,
                       authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    db = _database_required()
    try:
        document = await run_in_threadpool(db.analyses.find_one,
            {"business_id": account["business_id"], "request_id": request_id}, {"_id": 0})
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Analysis history is temporarily unavailable.") from exc
    if not document:
        raise HTTPException(status_code=404, detail="Analysis was not found in this business workspace.")
    return {**_public_analysis_summary(document), "result": document["result"]}



@app.get("/api/v1/analyses/{request_id}/chat")
async def get_analysis_chat(request_id: str,
                            authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    db = _database_required()
    scoped = {"business_id": account["business_id"], "request_id": request_id}
    try:
        analysis = await run_in_threadpool(db.analyses.find_one, scoped, {"_id": 1})
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis was not found in this business workspace.")
        cursor = await run_in_threadpool(lambda: db.analysis_messages.find(
            scoped, {"_id": 0, "role": 1, "content": 1, "created_at": 1}
        ).sort("created_at", 1).limit(100))
        messages = await run_in_threadpool(lambda: list(cursor))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Conversation history is temporarily unavailable.") from exc
    return {"request_id": request_id, "messages": [
        {"role": item["role"], "content": item["content"],
         "created_at": item["created_at"].isoformat() if isinstance(item.get("created_at"), datetime) else item.get("created_at")}
        for item in messages
    ]}


def _unavailable_llm_explanation(ml_result: dict) -> dict:
    """Build a transparent, evidence-only explanation when LLM output is unusable."""
    evidence = ml_result.get("evidence") if isinstance(ml_result.get("evidence"), list) else []
    limitations = ml_result.get("limitations") if isinstance(ml_result.get("limitations"), list) else []
    summary = ml_result.get("summary")
    summary = (
        str(summary).strip()
        if isinstance(summary, str) and summary.strip()
        else "The deterministic analysis completed, but its AI explanation could not be validated."
    )
    grounded_evidence = [str(item) for item in evidence[:8] if isinstance(item, str)]
    return {
        "summary": summary,
        "observations": grounded_evidence,
        "possible_causes": [],
        "supporting_evidence": grounded_evidence,
        "recommended_checks": [],
        "limitations": list(dict.fromkeys(
            [str(item) for item in limitations[:12] if isinstance(item, str)]
            + ["The local LLM response could not be validated. The deterministic ML report remains authoritative."]
        )),
        "confidence": "insufficient_evidence",
    }


def _fallback_chat_answer(question: str, ml_result: dict, prior_explanation: dict | None = None) -> dict:
    """Answer from saved deterministic evidence when local LLM inference is unavailable."""
    question_text = question.strip().lower()
    energy = ml_result.get("energy") if isinstance(ml_result.get("energy"), dict) else {}
    observations: list[str] = []
    limitations: list[str] = [
        "The local language model was unavailable; this response is assembled from the saved deterministic ML report."
    ]

    labels = (("forecast", "Forecast energy"), ("expected", "Expected energy"),
              ("actual", "Measured actual energy"), ("deviation", "Actual minus forecast"))
    energy_values = []
    for key, label in labels:
        component = energy.get(key) if isinstance(energy.get(key), dict) else {}
        value = component.get("value_kwh")
        reason = component.get("reason")
        if value is not None:
            observations.append(f"{label}: {value} kWh.")
            energy_values.append(f"{label.lower()} is {value} kWh")
        elif reason:
            observations.append(f"{label} is unavailable: {reason}")
            limitations.append(f"{label}: {reason}")

    anomalies = ml_result.get("anomalies") if isinstance(ml_result.get("anomalies"), list) else []
    hypotheses = ml_result.get("hypotheses") if isinstance(ml_result.get("hypotheses"), list) else []
    supported_causes = [str(item.get("summary") or item.get("hypothesis") or item.get("message"))
                        for item in hypotheses if isinstance(item, dict)
                        and (item.get("summary") or item.get("hypothesis") or item.get("message"))]
    if any(term in question_text for term in ("anomal", "inverter", "fault", "device", "underperform")):
        for item in anomalies[:8]:
            if isinstance(item, dict) and item.get("message"):
                observations.append(str(item["message"]))
        for item in hypotheses[:8]:
            if isinstance(item, dict):
                text = item.get("summary") or item.get("hypothesis") or item.get("message")
                if text:
                    observations.append(f"Candidate explanation (not a confirmed cause): {text}")
    elif not observations:
        summary = ml_result.get("summary")
        if isinstance(summary, str) and summary.strip():
            observations.append(summary.strip())

    if not anomalies and not hypotheses:
        limitations.append("The saved report does not contain a supported anomaly or root-cause hypothesis.")
    existing_limitations = ml_result.get("limitations")
    if isinstance(existing_limitations, list):
        limitations.extend(str(item) for item in existing_limitations[:8] if item)

    if energy_values and any(term in question_text for term in ("forecast", "waterfall", "deviation", "energy", "generation")):
        summary = "Based on the saved ML report, " + "; ".join(energy_values) + "."
    elif observations:
        summary = "Based on the saved deterministic analysis: " + " ".join(observations[:3])
    else:
        summary = "The saved analysis is available, but it does not contain enough evidence to answer this question reliably."

    prior_checks = (prior_explanation or {}).get("recommended_checks", [])
    checks = [str(item) for item in prior_checks[:6] if item] if isinstance(prior_checks, list) else []
    return {
        "summary": summary,
        "observations": observations[:10],
        "possible_causes": supported_causes[:8],
        "supporting_evidence": [str(item) for item in (ml_result.get("evidence") or [])[:8]],
        "recommended_checks": checks,
        "limitations": list(dict.fromkeys(limitations))[:12],
        "confidence": "moderate" if supported_causes else "insufficient_evidence",
    }


@app.post("/api/v1/analyses/{request_id}/chat")
async def ask_about_analysis(request_id: str, payload: AnalysisChatPayload = Body(...),
                             authorization: str | None = Header(None, alias="Authorization")) -> dict:
    account = _authorize_browser(authorization)
    question = payload.question.strip()
    if not question or len(question) > 2000:
        raise HTTPException(status_code=422, detail="Question must contain 1 to 2,000 characters.")
    db = _database_required()
    scoped = {"business_id": account["business_id"], "request_id": request_id}
    try:
        document = await run_in_threadpool(db.analyses.find_one, scoped, {"_id": 0})
        if not document:
            raise HTTPException(status_code=404, detail="Analysis was not found in this business workspace.")
        cursor = await run_in_threadpool(lambda: db.analysis_messages.find(
            scoped, {"_id": 0, "role": 1, "content": 1}
        ).sort("created_at", -1).limit(8))
        history = await run_in_threadpool(lambda: list(cursor))
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="Saved analysis is temporarily unavailable.") from exc

    saved = document.get("result") or {}
    ml_result = saved.get("ml_analysis")
    if not isinstance(ml_result, dict):
        raise HTTPException(status_code=422, detail="This saved report has no deterministic ML evidence for follow-up.")
    context = [
        f"{item['role'].upper()}: {str(item['content'])[:2000]}"
        for item in reversed(history)
    ]
    llm_payload = {
        "request_id": request_id,
        "plant_id": document.get("plant_id", "unknown-plant"),
        "timestamp": None,
        "plant_context": {
            "source": "saved_analysis_follow_up",
            "analysis_mode": document.get("analysis_mode"),
            "user_question": question,
        },
        "observations": {
            "analysis_status": ml_result.get("analysis_status"),
            "summary": ml_result.get("summary"),
            "data_quality": ml_result.get("data_quality", {}),
            "limitations": ml_result.get("limitations", []),
            "unresolved_fields": ml_result.get("unresolved_fields", []),
            "prior_explanation": saved.get("analysis", {}),
        },
        "ml_results": _compact_ml_for_llm(ml_result),
        "retrieved_context": context[-8:],
    }
    model_name = "local-llm"
    try:
        explanation = await _post_llm(llm_payload)
        validated = AnalyzeResponse.model_validate({
            **explanation, "request_id": request_id,
            "plant_id": document.get("plant_id", "unknown-plant"),
        })
        answer = validated.analysis.model_dump(mode="json")
        model_name = validated.model
    except HTTPException as exc:
        if exc.status_code not in {502, 503, 504}:
            raise
        answer = _fallback_chat_answer(question, ml_result, saved.get("analysis"))
        model_name = "deterministic-fallback"
    except Exception:
        answer = _fallback_chat_answer(question, ml_result, saved.get("analysis"))
        model_name = "deterministic-fallback"

    now = datetime.now(timezone.utc)
    records = [
        {"business_id": account["business_id"], "user_id": account["user_id"],
         "request_id": request_id, "role": "user", "content": question, "created_at": now},
        {"business_id": account["business_id"], "user_id": account["user_id"],
         "request_id": request_id, "role": "assistant",
         "content": answer, "created_at": now},
    ]
    try:
        await run_in_threadpool(db.analysis_messages.insert_many, records)
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="The answer was generated but the conversation could not be saved.") from exc
    return {"request_id": request_id, "answer": answer,
            "model": model_name, "created_at": now.isoformat()}


def _chat_answer_as_text(answer: dict) -> str:
    """Create a readable stream representation; the persisted answer remains structured."""
    sections = (
        ("What the readings tell us", "observations"),
        ("Possible explanations", "possible_causes"),
        ("Evidence considered", "supporting_evidence"),
        ("Recommended checks", "recommended_checks"),
        ("Limitations and uncertainty", "limitations"),
    )
    lines = [str(answer.get("summary") or "The model did not return a summary.")]
    for heading, key in sections:
        values = answer.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {str(value)}" for value in values if value)
    confidence = answer.get("confidence")
    if confidence:
        lines.extend(["", f"**Evidence confidence:** {str(confidence).replace('_', ' ')}"])
    return "\n".join(lines)


@app.post("/api/v1/analyses/{request_id}/chat/stream")
async def stream_analysis_chat(
    request_id: str,
    payload: AnalysisChatPayload = Body(...),
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Stream a grounded follow-up answer over SSE after the local model completes.

    Generation remains owned by the local LLM. The stream transports its completed,
    validated explanation progressively so the browser can render a live response.
    """
    result = await ask_about_analysis(request_id, payload, authorization)
    answer = result["answer"]
    rendered = _chat_answer_as_text(answer)

    async def events():
        yield "event: start\ndata: {}\n\n"
        for offset in range(0, len(rendered), 48):
            chunk = rendered[offset:offset + 48]
            yield "event: delta\ndata: " + json.dumps({"text": chunk}, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(0.015)
        yield "event: done\ndata: " + json.dumps({
            "answer": answer, "model": result.get("model"),
            "created_at": result.get("created_at"),
        }, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solarsleuth-application-backend"}


@app.get("/ready")
async def ready() -> dict:
    checks = {
        "ml_service_reachable": False,
        "llm_api_reachable": False,
        "model_loaded": False,
    }
    ml_status = "unreachable"
    llm_status = "unreachable"
    llm_error = None
    llm_model_name = None
    llm_adapter_available = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), trust_env=False) as client:
        try:
            response = await client.get(f"{ML_API_URL}/ready")
            response.raise_for_status()
            data = response.json()
            ml_status = str(data.get("status", "unknown"))
            checks["ml_service_reachable"] = ml_status == "ready"
        except (httpx.HTTPError, ValueError):
            pass
        try:
            response = await client.get(f"{LLM_API_URL}/ready")
            response.raise_for_status()
            data = response.json()
            llm_status = str(data.get("status", "unknown"))
            checks["llm_api_reachable"] = True
            checks["model_loaded"] = bool(data.get("model_loaded", False))
            llm_error = data.get("last_inference_error") or data.get("load_error")
            llm_model_name = data.get("model_name")
            llm_adapter_available = bool(data.get("adapter_available", False))
        except (httpx.HTTPError, ValueError):
            pass
    is_ready = (
        checks["ml_service_reachable"]
        and checks["llm_api_reachable"]
        and checks["model_loaded"]
        and llm_status == "ready"
    )
    return {
        "status": "ready" if is_ready else "degraded",
        "service": "solarsleuth-application-backend",
        "ml_status": ml_status,
        "llm_status": llm_status,
        "llm_error": llm_error,
        "llm_model_name": llm_model_name,
        "llm_adapter_available": llm_adapter_available,
        **checks,
    }

@app.post("/api/v1/analyze/upload", response_model=AnalyzeResponse)
async def analyze_upload(
    file: UploadFile = File(...),
    weather_file: UploadFile | None = File(None),
    forecast_file: UploadFile | None = File(None),
    devices_file: UploadFile | None = File(None),
    event_log_file: UploadFile | None = File(None),
    plant_id: str = Form("unknown-plant"),
    mode: str = Form("auto"),
    timezone: str | None = Form(None),
    interval_minutes: float | None = Form(None),
    sheet_name: str | None = Form(None),
    authorization: str | None = Header(None, alias="Authorization"),
) -> AnalyzeResponse:
    account = _authorize_browser(authorization)
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

    context_uploads = {
        "weather_file": weather_file,
        "forecast_file": forecast_file,
        "devices_file": devices_file,
        "event_log_file": event_log_file,
    }
    context_files: dict[str, tuple[str, bytes]] = {}
    total_size = len(content)
    for field, upload in context_uploads.items():
        if upload is None:
            continue
        context_name = _safe_filename(upload.filename)
        if Path(context_name).suffix.lower() not in {".csv", ".xlsx"}:
            await upload.close()
            raise HTTPException(status_code=415, detail=f"{field} must be a CSV or XLSX file.")
        context_content = await upload.read(MAX_UPLOAD_BYTES + 1)
        await upload.close()
        if not context_content:
            raise HTTPException(status_code=422, detail=f"{field} is empty.")
        total_size += len(context_content)
        if total_size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Combined upload exceeds the configured size limit.")
        _validate_file_signature(context_name, context_content)
        context_files[field] = (context_name, context_content)

    try:
        await asyncio.wait_for(ANALYSIS_SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="Analysis capacity is busy. Retry shortly.") from exc
    try:
        ml_result = await _run_ml(
            content, filename, plant_id=plant_id, mode=mode, timezone=timezone,
            interval_minutes=interval_minutes, sheet_name=sheet_name,
            context_files=context_files,
        )
        ml_status = ml_result.get("analysis_status")
        if ml_status in {"invalid_input", "failed"}:
            raise HTTPException(status_code=422, detail="The uploaded dataset did not pass deterministic ML validation.")
        if ml_status not in {"success", "partial"}:
            raise HTTPException(status_code=502, detail="The ML service returned an unknown analysis status.")
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
        except HTTPException as exc:
            if exc.status_code not in {502, 503, 504}:
                raise
            validated = AnalyzeResponse(
                request_id=request_id,
                plant_id=plant_id,
                model="deterministic-fallback",
                analysis=_fallback_chat_answer("Explain the deterministic ML analysis and energy deviation.", ml_result),
                ml_analysis=ml_result,
                analysis_mode=ml_result.get("analysis_mode"),
            )
        except Exception:
            # A malformed or schema-invalid LLM response must never discard a valid
            # deterministic ML result. Keep the report usable and make the AI limitation explicit.
            validated = AnalyzeResponse(
                request_id=request_id,
                plant_id=plant_id,
                model="deterministic-fallback",
                analysis=_fallback_chat_answer("Explain the deterministic ML analysis and energy deviation.", ml_result),
                ml_analysis=ml_result,
                analysis_mode=ml_result.get("analysis_mode"),
            )
        await _persist_analysis(account, filename, plant_id, validated)
        return validated
    finally:
        ANALYSIS_SLOTS.release()