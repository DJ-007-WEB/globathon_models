# Backend — Solar Recovery Intelligence

## Status

The first backend API implementation is on this `backend` branch. It validates frontend requests, forwards them to the existing local LLM API, normalizes the response contract, and returns useful errors when the LLM is unavailable.

**The teammate's ML implementation is not called or modified.** The backend accepts optional `ml_results`; it is currently safe to use sample data while ML development continues.

## Architecture

```text
Frontend (Vite/React: usually http://localhost:5173)
        |
        | POST /api/v1/analyze
        v
Application backend (http://127.0.0.1:8001)
        |
        | POST /api/v1/analyze
        v
Local LLM API (http://127.0.0.1:8000)
```

The backend must run on a machine that can reach the local LLM API. For this hackathon setup, run both services on the same development laptop. A deployed backend's `127.0.0.1` would refer to the deployment server, not your laptop.

## Run the backend

Use a separate working directory/clone for this `backend` branch if you also need the `AI-model` branch checked out locally at the same time.

PowerShell, from the repository root on the `backend` branch:

```powershell
py -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Start the local LLM API separately from the `AI-model` working copy on port 8000. Follow `README_LOCAL_API.md` on that branch. The first inference can take longer while the model loads.

Open [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

## Endpoints

- `GET /health`: backend liveness; does not require the LLM to be online.
- `GET /ready`: checks the upstream LLM API and whether its model is loaded.
- `POST /api/v1/analyze`: validates the request, forwards it to the local LLM, validates the response, and returns a stable JSON envelope.

## Sample request

```json
{
  "plant_id": "SOLAR-TEST-01",
  "timestamp": "2026-10-30T12:00:00+05:30",
  "plant_context": {
    "installed_capacity_kw": 500
  },
  "observations": {
    "panel_temperature_c": 58,
    "power_output_kw": 65,
    "expected_power_output_kw": 100
  },
  "ml_results": {},
  "retrieved_context": []
}
```

These are sample values only. The backend does not calculate expected output or diagnose faults; it forwards observations and any supplied ML outputs to the explanation API.

## Error handling

- `422`: request schema validation failed.
- `502`: upstream returned an invalid response or unexpected error.
- `503`: local LLM API is unavailable or not ready.
- `504`: local LLM request timed out.

If the browser blocks a request, ensure the frontend's exact origin is listed in `CORS_ORIGINS` in `.env`. Origins include the protocol and port, for example `http://localhost:5173`.

## Tests

```powershell
python -m pip install pytest httpx
python -m pytest -q
```

The tests mock the LLM call and validate the backend contract; they do not load the GPU model or test ML behavior.

## Environment

- `LLM_API_URL`: default `http://127.0.0.1:8000`
- `LLM_TIMEOUT_SECONDS`: default `180`
- `CORS_ORIGINS`: comma-separated allowed frontend origins

Never commit `.env`, model weights, virtual environments, private plant data, or secrets.
