# Local LLM API — SolarSleuth Explanation Service

This branch provides the local language-model explanation layer on port **8000**. It receives structured observations and the deterministic ML contract from the application backend. It does not ingest datasets or calculate energy metrics.

## Start

From the AI-model branch root:

```powershell
py -m venv .venv-ai
.\.venv-ai\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Set `INTERNAL_SERVICE_TOKEN` to the same value configured in backend and ML service. In development it may be empty; with `ENVIRONMENT=production`, the service refuses unauthenticated internal inference calls.

## Configuration

- `MODEL_NAME`: default `Qwen/Qwen3.5-0.8B`
- `ADAPTER_PATH`: default `models/solar-qwen-lora-final`
- `INTERNAL_SERVICE_TOKEN`: shared internal service secret
- `ENVIRONMENT`: development or production

The service loads the configured model and adapter lazily on the first inference. Confirm that the adapter directory contains `adapter_config.json` and is compatible with the selected base model. The repository does not include model weights or certify that a developer's local adapter path exists. A missing or incompatible adapter causes an explicit service error; it must not be described as a successful model load.

## Endpoints

- `GET /health`: liveness
- `GET /ready`: reports whether model weights have loaded
- `POST /api/v1/analyze`: authenticated internal explanation endpoint

The system prompt treats `ml_results` as authoritative and prohibits arithmetic or changing supplied numerical values. It explains possible causes only as hypotheses and reports evidence, checks and limitations.

## Tests

```powershell
python -m pip install httpx pytest
python -m pytest -q
```

Tests mock inference and do not certify GPU execution, adapter compatibility, explanation quality or model accuracy. Keep weights, datasets, `.env`, and private plant data out of Git.
