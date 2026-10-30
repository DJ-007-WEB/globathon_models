# SolarSleuth Deterministic ML Service

The ML branch owns all deterministic data calculations. The application backend calls this service before it calls the local LLM.

## HTTP service (port 8002)

From the repository's `ML-models` directory:

```powershell
python -m venv .venv-ml
.\.venv-ml\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8002
```

The API exposes `GET /health`, `GET /ready`, and `POST /api/v1/analyze` (multipart upload). The upload endpoint accepts one CSV or XLSX operating-data file, plus `plant_id`, `mode`, optional IANA `timezone`, `interval_minutes`, and `sheet_name`. Maximum upload size is 25 MiB by default.

Set `INTERNAL_SERVICE_TOKEN` to the same value configured in the backend and AI-model services. In development, an unset token is allowed. Set `ENVIRONMENT=production` to require a configured token. This is service-to-service authentication, not user authentication.

The endpoint writes the upload to a random temporary file, calls the existing `src.pipeline.run_pipeline` boundary, and removes the temporary file. It does not alter the ML algorithms. The versioned contract-v2 result is returned unchanged.

## Scope of the HTTP adapter

The Python pipeline can accept a scenario directory or a mapping containing operating, weather, device, forecast, event-log and metadata inputs. The current HTTP adapter deliberately accepts only one operating-data CSV/XLSX file. Multi-file upload roles are not exposed over HTTP yet; missing context must remain unavailable rather than being fabricated.

## Responsibilities

Ingestion, adaptive schema mapping, data validation, physics baseline, anomaly detection, evidence-based attribution and energy waterfall calculations remain in this branch. The LLM is not used for arithmetic, and synthetic benchmarks must not be represented as real-world accuracy.

Run the existing tests from this directory:

```powershell
python -m pytest -q
```
