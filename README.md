# Backend — SolarSleuth Application API

This branch owns the frontend-facing API on port **8001**. It validates requests, accepts uploads, calls the deterministic ML service first, passes the ML contract to the local LLM for explanation, and returns both outputs to the frontend.

## End-to-end request flow

```text
React/Vite :5173
  POST /api/v1/analyze/upload (multipart CSV/XLSX)
        |
        v
Application backend :8001
  validate extension / size / options
        |
        | POST /api/v1/analyze (multipart + X-Service-Token)
        v
Deterministic ML :8002
  ingestion -> schema mapping -> validation -> physics baseline
  -> anomaly detection -> attribution -> energy waterfall
        |
        | contract v2 JSON
        v
Application backend :8001
  passes ML contract as ml_results (does no arithmetic)
        |
        | POST /api/v1/analyze + X-Service-Token
        v
Local LLM :8000
  explanation, possible causes, evidence, technician checks, limitations
        |
        v
Frontend receives analysis + ml_analysis + analysis_mode
```

Manual structured input remains available at `POST /api/v1/analyze`. Dataset upload is `POST /api/v1/analyze/upload`.

## Run

Use a separate working copy for each branch so all four services can run simultaneously. From the backend branch root:

```powershell
py -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set INTERNAL_SERVICE_TOKEN to the same secret used by ML and AI-model.
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

## Configuration

- `ML_API_URL`: default `http://127.0.0.1:8002`
- `ML_TIMEOUT_SECONDS`: default 300
- `LLM_API_URL`: default `http://127.0.0.1:8000`
- `LLM_TIMEOUT_SECONDS`: default 180
- `INTERNAL_SERVICE_TOKEN`: shared service-to-service secret
- `ENVIRONMENT`: `development` or `production`; production requires the token
- `MAX_UPLOAD_BYTES`: default 25 MiB
- `CORS_ORIGINS`: exact Vite origins

The token is sent only between backend and internal services; it is never placed in browser code. Development may run without a token. Set the same high-entropy token in all three Python services before using production mode.

## Response

The upload response preserves the complete deterministic ML contract under `ml_analysis`, the LLM explanation under `analysis`, and the selected `analysis_mode`. A partial ML result is still explained with its limitations. Invalid or failed ML input is rejected before the LLM is called.

## Scope and security

The current HTTP upload accepts one operating-data CSV/XLSX file per request. The underlying Python ML pipeline supports richer in-memory/scenario inputs, but multi-file weather/device/forecast/event-log upload is not yet exposed over HTTP.

The existing frontend login is browser-local demo authentication, not server-side identity or authorization. Bind local services to loopback for development. A public deployment still needs real user authentication/authorization, HTTPS/private service networking, rate limiting and managed secrets. Do not expose this prototype to confidential plant data until those controls are implemented.

## Tests

```powershell
python -m pip install pytest httpx
python -m pytest -q
```

Tests mock upstream services; they do not certify real ML output, local model weights, or full-machine end-to-end operation.
