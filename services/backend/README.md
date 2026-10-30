# Backend — SolarSleuth Application API

This branch owns the only browser-facing API on port **8001**. The browser sends uploads here; it never calls the ML or LLM services directly.

## Request pipeline

```text
React/Vite :5173
  POST /api/v1/analyze/upload (multipart CSV/XLSX)
        |
        v
Application backend :8001
  browser access gate -> metadata/file checks -> bounded concurrency
        |
        | POST /api/v1/analyze + X-Service-Token
        v
Deterministic ML :8002
  ingestion -> schema mapping -> validation -> physics baseline
  -> anomaly detection -> attribution -> energy waterfall
        |
        | validated success/partial contract
        v
Application backend :8001
  preserve full ML result; compact bounded evidence for LLM
        |
        | POST /api/v1/analyze + X-Service-Token
        v
Local LLM :8000
  explanation only; no arithmetic or metric modification
        |
        v
Frontend receives unchanged ml_analysis + structured analysis

If LLM is unavailable after valid ML completes, the backend returns the ML result
with an explicit explanation-unavailable response. Invalid/failed ML never reaches LLM.
```

## Run locally

From this branch root in PowerShell:

```powershell
py -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Start ML on 127.0.0.1:8002 and local LLM on 127.0.0.1:8000 before testing a full analysis. The backend itself can start while dependencies are offline; `/ready` reports degraded until both APIs respond.

## Configuration

- `ML_API_URL`, `ML_TIMEOUT_SECONDS`: deterministic ML service URL and timeout.
- `LLM_API_URL`, `LLM_TIMEOUT_SECONDS`: local explanation service URL and timeout.
- `INTERNAL_SERVICE_TOKEN`: shared high-entropy secret used only backend-to-ML/LLM.
- `API_ACCESS_TOKEN`: optional local-development browser API gate; required in production. Send it as `Authorization: Bearer <token>` from a trusted client.
- `ENVIRONMENT`: `development` or `production`; production fails closed without both secrets.
- `MAX_UPLOAD_BYTES`: default 25 MiB.
- `MAX_CONCURRENT_ANALYSES`: bounded in-process analysis concurrency (default 2).
- `CORS_ORIGINS`: comma-separated exact browser origins.

Generate secrets with a cryptographically secure random generator and use the same `INTERNAL_SERVICE_TOKEN` in backend, ML and AI-model. Never commit `.env`.

## Security boundary and honest limitations

- Services bind to loopback in the supplied local run commands. Keep ML/LLM private; do not expose ports 8000/8002 to browsers or the public internet.
- The backend validates extension, filename, upload size, basic file signature/CSV header, options, and response shape. The ML service remains responsible for parsing, schema mapping, unit inference and physical validation.
- Uploaded bytes are held in bounded memory only by the orchestrator and forwarded to ML; the backend does not persist uploads or log their contents.
- Internal service authentication uses constant-time token comparison in ML and LLM. The backend sends the token only on server-to-server requests.
- The browser access token is a deployment gate, **not** real multi-user identity, session management, or role-based authorization. The current frontend demo login is browser-local and is not a security control. Before real production/customer data: integrate an identity provider (OIDC/OAuth), validate signed user tokens and roles server-side, add per-user/tenant authorization and storage isolation, HTTPS/private networking, distributed rate limiting, audit logging, managed secrets, and dependency scanning.
- CORS is not authentication. Do not treat it as an access-control boundary.
- Current upload contract is one operating-data CSV/XLSX file. Multi-file weather/device/forecast/event-log ingestion and grounded follow-up chat are not exposed by this HTTP API.

## Tests

```powershell
pip install pytest httpx
python -m pytest -q
```

Tests mock ML and LLM. They verify orchestration, failure isolation, upload checks and access-gate behaviour; they do not certify model accuracy, adapter compatibility, or full-machine end-to-end operation.
