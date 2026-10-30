# SolarSleuth local LLM explanation service

Private FastAPI service on `127.0.0.1:8000`. It explains bounded deterministic ML evidence and does not calculate or modify plant metrics.

## Install and start (PowerShell)

From this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# Install a compatible PyTorch build for your machine (CUDA or CPU).
pip install -r requirements-api.txt
Copy-Item .env.example .env
# Copy the complete PEFT adapter into models/solar-qwen-lora-final
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

A complete adapter export must include `adapter_config.json` and adapter weights. The repository intentionally excludes model weights and private training artifacts. Set `ADAPTER_PATH` to another local adapter directory if needed. The adapter configuration's base model is used unless `MODEL_NAME` is explicitly set to the exact same model.

## API and security

- `GET /health`: process liveness
- `GET /ready`: adapter/model readiness
- `POST /api/v1/analyze`: explanation request from backend only

Set the same `INTERNAL_SERVICE_TOKEN` in backend, ML and LLM. Never put it in frontend code or expose this port publicly.

## Tests

```powershell
pip install pytest httpx
python -m pytest -q tests
```

Tests mock model inference and validate the request/response contract and service-token behavior. They do not prove that the local adapter can load or that GPU inference works.
