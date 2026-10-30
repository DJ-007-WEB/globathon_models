# AI Model — SolarSleuth Local LLM Explanation Service

This branch owns the explanation-only local language-model API on **127.0.0.1:8000**. The application backend is the only caller. The LLM receives bounded structured observations and the deterministic ML result; it never receives the raw uploaded file and is not allowed to calculate or alter plant metrics.

## Integration contract

The backend calls:

```text
POST http://127.0.0.1:8000/api/v1/analyze
Content-Type: application/json
X-Service-Token: <shared INTERNAL_SERVICE_TOKEN>
```

Request fields are `request_id`, `plant_id`, `timestamp`, `plant_context`, `observations`, `ml_results`, and `retrieved_context`. The request schema rejects extra fields and caps the serialized evidence payload at 60,000 characters. The response is:

```json
{
  "request_id": "backend-request-id",
  "plant_id": "plant-id",
  "model": "resolved-base-model",
  "analysis": {
    "summary": "Evidence-based explanation",
    "observations": [],
    "possible_causes": [],
    "supporting_evidence": [],
    "recommended_checks": [],
    "limitations": [],
    "confidence": "low"
  }
}
```

The backend's response contract is preserved. Numeric authority remains with the ML service; the LLM explanation is returned separately.

## Model and adapter setup

The repository intentionally does not contain model weights, private datasets, or the trained adapter. Copy the complete PEFT adapter export to `models/solar-qwen-lora-final` (or set `ADAPTER_PATH` in `.env`). A valid adapter directory must contain at least:

- `adapter_config.json`
- `adapter_model.safetensors` (or another PEFT-supported adapter weight file)

The service reads `base_model_name_or_path` from `adapter_config.json` by default. This avoids silently loading a different base model. Set `MODEL_NAME` only if it exactly matches the base model recorded in the adapter configuration. The adapter tokenizer is used when tokenizer files are present; otherwise the base model tokenizer is loaded.

If the training export contains only `adapter_model.safetensors`, it is incomplete for this service. Export/copy the full PEFT adapter directory, including `adapter_config.json`; do not guess the base model.

## Windows 11 local setup (Python 3.11)

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv-ai
.\.venv-ai\Scripts\Activate.ps1
python -m pip install --upgrade pip

# RTX 4050 / CUDA 12.8 build. If using CPU-only inference, install torch from PyPI instead.
python -m pip install torch --index-url https://download.pytorch.org/whl/cu128

python -m pip install -r requirements-api.txt
Copy-Item .env.example .env
```

The CUDA wheel must match the supported CUDA runtime/driver on the machine. Verify the installed build:

```powershell
python -c "import torch; print('Torch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

Configure `.env`. Leave `MODEL_NAME` blank to use the adapter's recorded base model. Set `ADAPTER_PATH` to the directory containing `adapter_config.json`. Use the same `INTERNAL_SERVICE_TOKEN` in backend, ML and LLM services; it may be blank only in local development.

## Tests

```powershell
python -m pip install pytest httpx
python -m pytest -q
```

Tests mock model inference and verify the API contract, backend payload compatibility, request limits, output schema, and internal service authentication. They do not certify adapter compatibility, GPU loading, explanation quality, or model accuracy.

## Start

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Endpoints:

- `GET /health`: process liveness.
- `GET /ready`: model-loaded and adapter-availability status.
- `POST /api/v1/analyze`: authenticated internal explanation endpoint.

The model is loaded lazily on the first analysis request. Before that, `/ready` reports `not_loaded`; after a failed load it reports `not_ready`. A healthy process does not mean model weights are loaded. The backend may start while the model is not loaded, but an analysis request requires successful model and adapter loading.

Keep the service bound to loopback. Do not expose port 8000 to the browser or public internet. Keep `.env`, datasets, model weights, and adapter files out of Git.
