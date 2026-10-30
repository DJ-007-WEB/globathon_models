# Backend — Solar Recovery Intelligence

## Architecture

The backend is the only public-facing application API. It preserves the existing manual-reading endpoint and adds a dataset-upload workflow.

```text
React/Vite frontend :5173
        |
        | multipart CSV/XLSX upload
        v
Application backend :8001
        |
        | private multipart request + service token
        v
Deterministic ML service :8002
        |
        | versioned contract-v2 JSON
        v
Application backend :8001
        |
        | compact structured ML evidence only
        v
Local LLM API :8000
        |
        | structured natural-language explanation
        v
Frontend: ML metrics + human-readable response
```

**Responsibility boundary:** Energy calculations, baselines, anomaly detection, attribution and waterfall arithmetic remain in the ML pipeline. The LLM receives the ML results and explains them; it must not calculate or overwrite numeric results.

## Run locally (PowerShell)

Use separate terminals / working copies for the three branches/services.

1. **ML service** — from the repository root:
   ```powershell
   cd ML-models
   python -m pip install -r requirements.txt
   $env:INTERNAL_SERVICE_TOKEN="use-the-same-long-random-secret-in-all-services"
   python -m uvicorn api:app --host 127.0.0.1 --port 8002
   ```

2. **LLM API** — from the AI-model working copy:
   ```powershell
   $env:INTERNAL_SERVICE_TOKEN="use-the-same-long-random-secret-in-all-services"
   python -m uvicorn api:app --host 127.0.0.1 --port 8000
   ```
   Configure `MODEL_NAME` and `ADAPTER_PATH` for the actual local base model and compatible adapter.

3. **Application backend** — from this branch:
   ```powershell
   python -m venv .venv-backend
   .\.venv-backend\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item .env.example .env
   # Set INTERNAL_SERVICE_TOKEN in .env to the same secret used by ML and AI.
   python -m uvicorn main:app --host 127.0.0.1 --port 8001
   ```

4. **Frontend** — from the frontend branch:
   ```powershell
   npm install
   npm run dev
   ```

The three Python services should run on the same development machine for the default loopback URLs. Do not expose ports 8000 or 8002 publicly.

## Endpoints

- `GET /health`: backend liveness.
- `GET /ready`: checks reachability of both internal services.
- `POST /api/v1/analyze`: backward-compatible manual-reading explanation path.
- `POST /api/v1/analyze/upload`: CSV/XLSX upload → ML analysis → local LLM explanation.

Upload fields: `file`, `plant_id`, optional `mode` (`auto`, `snapshot`, `full`), `timezone`, `interval_minutes`, and `sheet_name`.

Maximum upload size defaults to 25 MiB. Only CSV and XLSX are accepted. The backend does not persist uploaded files; the ML service uses a random temporary file and removes it in a `finally` block. The LLM receives a bounded structured summary of ML output, not the raw dataset.

## Security boundary and deployment requirements

- Keep all three service ports private; bind to loopback locally.
- Set the same high-entropy `INTERNAL_SERVICE_TOKEN` in backend, ML and AI services. Production mode refuses internal calls when the token is missing.
- Configure exact CORS origins; CORS is not authentication.
- Never commit `.env`, credentials, model weights, or private plant datasets.
- Use HTTPS/TLS and private networking if services run on separate hosts.
- The current frontend sign-in is a browser-local demo gate, not real user authentication. This prototype therefore must not be exposed as a public multi-tenant service handling confidential plant data until server-side user authentication/authorization, rate limiting, audit policy and deployment secret management are added.
- Do not log request bodies, uploaded file contents, or model prompts. Application errors returned to clients intentionally avoid internal URLs and stack traces.

## Tests

Backend tests should be run with `python -m pytest -q`. The ML service has its own test suite under `ML-models/tests`. These changes have not yet been executed in a local runtime; run both suites and a real CSV/XLSX smoke test before deployment.
