# SolarSleuth backend

FastAPI application API on `127.0.0.1:8001`. It is the only browser-facing service and orchestrates deterministic ML followed by the explanation-only local LLM.

## Start

From this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Configure MONGODB_URI and JWT_SECRET in .env
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

## Responsibilities

- MongoDB-backed registration/login, Argon2 password hashes and signed expiring JWTs.
- Business-scoped plant directory and metadata updates.
- One-file CSV/XLSX upload validation and bounded ML-first orchestration.
- Persistent analysis history and report-grounded follow-up chat.
- The browser never receives the internal service token and never calls ML/LLM directly.

## Downstream services

- ML: `ML_API_URL=http://127.0.0.1:8002`
- LLM: `LLM_API_URL=http://127.0.0.1:8000`
- Set the same `INTERNAL_SERVICE_TOKEN` in all three backend services. It may be blank only in local development.

## Tests

```powershell
pip install pytest httpx
python -m pytest -q
```

Tests mock downstream APIs and MongoDB boundaries where appropriate. A passing test suite does not prove live MongoDB connectivity or model inference.
