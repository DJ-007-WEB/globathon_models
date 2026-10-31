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

## How an explanation is generated

The backend sends a bounded digest of the deterministic ML result. The service turns it into a short
plain-English **evidence brief** (status, energy totals, per-inverter results, alert periods with logged
events, unconfirmed ML hypotheses, data-quality issues, limitations). It never sends raw JSON to the model.
Then it tries, in order, until one answer is valid and grounded:

1. **Fine-tuned adapter, training format**: the same short system prompt and "Plant observations: …" user
   message the LoRA adapter was trained on (see `test_local_adapter.py`, `generate_dataset.py`).
2. **Fine-tuned adapter, JSON-primed**: the assistant turn is started with `{"summary": "` and an immediate
   end-of-sequence is suppressed, so the model cannot return an empty answer.
3. **Base model with the adapter disabled**: full evidence rules, JSON-primed.

**Follow-up chat questions use a different order:** the base model answers first and the adapter is the fallback.
The adapter was fine-tuned only to analyse a case (never to answer a question), so it returns the same style of
analysis whatever is asked.

An attempt is rejected when it is empty, not valid JSON, one of the adapter's memorized synthetic training
answers, or a near-repeat of an earlier answer in the same conversation. The adapter's fixed training checks
(e.g. "Verify timestamps, units and sensor-quality flags") are removed from lists. Statements quoting numbers that are not in the ML result are removed. The service stops starting new
attempts once `LLM_TIME_BUDGET_SECONDS` (default 240) would be exceeded, so the backend's 300-second timeout
is not hit. If every attempt fails, `/ready` → `last_inference_error` lists what each attempt produced, and the
backend shows its evidence-only answer instead.

| Setting | Default | Meaning |
|---|---|---|
| `LLM_ADAPTER_MODE` | `auto` | `auto` = adapter first, base fallback; `adapter` or `base` pins one path |
| `LLM_TIME_BUDGET_SECONDS` | `240` | stop starting new attempts after this long |
| `MAX_NEW_TOKENS` | `700` | answer length; too small truncates the JSON |
| `MAX_INPUT_TOKENS` | `7600` | prompt budget |

`/ready` → `last_generation_path` shows which attempt produced the last answer.

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
