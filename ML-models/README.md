# SolarSleuth Deterministic ML Service

The ML branch owns all deterministic data calculations. The application backend calls this service first and forwards only bounded, validated ML evidence to the local LLM.

## HTTP service (port 8002)

Run these commands from the repository's `ML-models` directory in PowerShell:

```powershell
py -3.11 -m venv .venv-ml
.\.venv-ml\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8002 --reload
```

The API exposes:

- `GET /health` — process liveness.
- `GET /ready` — whether the deterministic pipeline is importable.
- `POST /api/v1/analyze` — multipart upload of one CSV or XLSX operating-data file.

The upload endpoint accepts `file`, `plant_id`, `mode` (`auto`, `snapshot`, or `full`), optional IANA `timezone`, positive `interval_minutes`, and optional Excel `sheet_name`. The default upload limit is 25 MiB and the default concurrent-analysis limit is 2. The service performs a bounded read, basic content/signature checks, safe temporary-file handling, and guaranteed temporary-file cleanup. Unexpected parser/pipeline exceptions are returned as a generic error; internal paths and stack traces are not exposed.

## Backend connection

The application backend runs on port 8001 and calls:

```text
POST http://127.0.0.1:8002/api/v1/analyze
X-Service-Token: <shared INTERNAL_SERVICE_TOKEN>
Content-Type: multipart/form-data
```

Set the same `INTERNAL_SERVICE_TOKEN` in the backend, ML service, and AI-model service when using service authentication. In local development the token may remain blank. In production set `ENVIRONMENT=production` and configure a high-entropy token in all services. This token authenticates service-to-service calls; it is not end-user authentication.

## Deterministic pipeline

The HTTP adapter calls the existing `src.pipeline.run_pipeline` compatibility boundary, which delegates to `src.service.analyze`. The analysis stages are:

1. CSV/XLSX ingestion, header and timestamp discovery.
2. Auditable schema/alias mapping and explicit unit conversion.
3. Data-quality validation (missing values, duplicates, timestamp order/gaps, physical plausibility and related checks).
4. Device/weather context merge where available.
5. Deterministic physics-based expected power and energy baseline.
6. Anomaly detection with evidence and capability limitations.
7. Evidence-based attribution hypotheses (not unsupported root-cause claims).
8. Forecast/expected/actual energy comparison and reconciled waterfall.
9. Strict contract-v2 validation and JSON-safe serialization.

Numerical authority stays in ML. Missing values remain null; forecast, expected and actual energy are independent; power-to-energy conversion uses the measured timestamp interval; ambiguous units are not guessed. The LLM is not used for arithmetic.

The current HTTP adapter deliberately accepts only one operating-data file. Although the Python pipeline can consume role-labelled scenario directories/mappings, multi-file weather/device/forecast/event-log inputs are not yet exposed through this route. Do not claim multi-file HTTP ingestion until the API and backend both implement it.

## Install and test

```powershell
python -m pytest -q
```

The suite covers the deterministic pipeline, contract, schema mapping, validation, energy calculations, anomalies, attribution, upload validation, authentication, bounded uploads and temporary-file cleanup. GitHub Actions runs the same test suite on pushes and pull requests to `ML_models`.

Synthetic benchmark results are not real-world accuracy claims. The active expected-energy method is the documented physics baseline; LightGBM is not used as a trained production model.
