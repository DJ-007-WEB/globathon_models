# SolarSleuth

SolarSleuth analyses solar-plant operating data using a deterministic ML pipeline and produces evidence-grounded explanations with a locally hosted LLM.

## Repository layout

```text
.
├── frontend/       # React + Vite UI (5173)
├── backend/        # Browser-facing FastAPI, auth, MongoDB, orchestration (8001)
├── ml-service/     # Deterministic energy analysis API (8002)
├── llm-service/    # Local LLM explanation API (8000)
├── scripts/        # Root-level developer/test helpers
├── .github/        # Integration CI
├── README.md
└── INTEGRATION_BASELINE.md
```

## Architecture and safety boundaries

The browser talks **only** to the backend. The backend validates uploads, invokes deterministic ML first, and then passes bounded ML evidence to the LLM. ML is the sole numerical authority; the LLM explains and must not calculate or modify energy metrics. If the LLM is unavailable after a valid ML result, the backend preserves the ML result and returns an explicit explanation-unavailable response.

The upload contract accepts one required operating-data CSV/XLSX file plus optional weather, forecast, device and event-log CSV/XLSX files (25 MiB combined). The ML response contract is version 2.1.0 and includes per-inverter measured energy, physics-based expected energy and their difference when device identifiers are available; the per-device measured and expected totals reconcile to the corresponding plant totals. Each analysis must contain at most one non-empty `scenario_id`; mixed scenario IDs are rejected with an actionable validation error rather than silently combined into misleading plant totals. Upload each simulation scenario separately. The raw upload is not persisted. Auth, plants, saved analysis reports and report-grounded follow-up conversations are MongoDB-backed and scoped to the authenticated business workspace. The trained LoRA adapter and model weights are intentionally not committed.

## Requirements

- Windows 11 PowerShell or Linux/macOS shell
- Python 3.11
- Node.js 20+
- MongoDB Atlas or a local MongoDB instance for registration, login, plants, reports and chat
- For real local LLM inference: compatible PyTorch/Transformers dependencies and the complete PEFT adapter export, including `adapter_config.json` and adapter weights. GPU is optional; CPU inference may be slow.

## Configure environment

Copy each example file and configure it locally. Do not commit any `.env` file or secrets.

**PowerShell (from repository root):**

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item ml-service/.env.example ml-service/.env
Copy-Item llm-service/.env.example llm-service/.env
```

**Linux/macOS:**

```bash
cp backend/.env.example backend/.env
cp ml-service/.env.example ml-service/.env
cp llm-service/.env.example llm-service/.env
```

Set `MONGODB_URI` and a unique `JWT_SECRET` (at least 32 characters) in `backend/.env`. Generate a secret with:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use the **same** high-entropy `INTERNAL_SERVICE_TOKEN` in backend, ML and LLM `.env` files. Blank is accepted only for local development. Keep secrets out of frontend code and Git.

For the LLM, place the complete adapter at `llm-service/models/solar-qwen-lora-final`, or set `ADAPTER_PATH` in `llm-service/.env`. The model weights are not included in this repository.

## Install and start all four services (PowerShell)

Open four terminals from the repository root.

### 1. ML service — port 8002

```powershell
cd ml-service
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8002 --reload
```

### 2. LLM service — port 8000

```powershell
cd llm-service
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# Install the PyTorch build appropriate for your machine first.
pip install -r requirements-api.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

The lightweight API tests do not need model weights. For live inference, the complete adapter and its compatible base model must be available.

### 3. Backend — port 8001

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

### 4. Frontend — port 5173

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. The frontend uses the backend at http://127.0.0.1:8001 by default.

## Test each service

Run the tests from each service directory (use separate virtual environments as above):

```powershell
# Frontend: type-check + production build
cd frontend
npm run build

# Backend API/auth/history/plant/chat tests
cd ../backend
pip install pytest httpx
python -m pytest -q

# LLM API contract/auth tests (mock inference; no adapter required)
cd ../llm-service
pip install pytest httpx
python -m pytest -q tests

# Deterministic ML pipeline/API tests
cd ../ml-service
python -m pytest -q
```

For an aggregate run, first create and install the service environments as described above, then run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-all.ps1
```

The script uses each service's `.venv` when present and returns a non-zero exit code if any suite fails.

## Smoke-test service health

In another PowerShell terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8002/health
Invoke-RestMethod http://127.0.0.1:8002/ready
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/ready
```

A process health response is not proof the model is loaded. For live LLM inference, `/ready` must report `model_loaded: true`. Backend `/ready` reports downstream dependency state.

## Verify the standard local runtime (Windows PowerShell)

After starting the four services on ports 8000, 8001, 8002 and 5173, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-local-runtime.ps1
```

The script checks the listening process/interpreter for each port, the 300-second backend LLM timeout, matching non-empty internal service tokens (without printing them), both trusted CORS origins, LLM warmup, backend dependency readiness and the Vite HTTP response. It exits non-zero if any check fails. It does not change local environment files or expose secret values.

## End-to-end acceptance test

1. Confirm all four services are running and backend `/ready` can reach ML and LLM.
2. Register a new account in the UI. Registration/login requires working MongoDB configuration.
3. Sign in and create a plant in the Plants page.
4. Upload a valid CSV/XLSX operating-data file and select that registered plant.
5. Confirm the deterministic ML section displays the returned metrics, data quality, anomalies, hypotheses and limitations.
6. Confirm the explanation section is present. If the local adapter is unavailable, the valid ML result should still be retained with an explicit explanation-unavailable state.
7. Open Reports, reopen the saved analysis, and verify it survives a page refresh/sign-in.
8. Ask a follow-up question in the AI explanation workspace and verify it is tied to the selected saved report.
9. Select a plant and inspect its plant-scoped report history.

Never interpret an ML hypothesis as a confirmed equipment fault. Confirm findings against plant telemetry and qualified operators.

## Saved-analysis assistant chat

The browser loads a report-scoped conversation from
`GET /api/v1/analyses/{request_id}/chat`. Follow-up questions can use the
streaming transport:

```http
POST /api/v1/analyses/{request_id}/chat/stream
Authorization: Bearer <browser-access-token>
Content-Type: application/json

{"question":"Why is measured output below expected energy?"}
```

The backend reuses the authenticated saved-analysis chat workflow, so the
question and validated assistant answer are persisted against that report.
The SSE stream sends `delta` events containing readable answer text and a
final `done` event containing the structured answer. The local model still
finishes generation and schema validation before these display chunks are
sent; this is progressive browser delivery, not token-by-token model decoding.
The frontend renders the stream with React elements (no HTML injection) and
then switches to the structured explanation view.

## API documentation

With a service running, open:
- Backend: http://127.0.0.1:8001/docs
- ML: OpenAPI docs are disabled on this private service; use `/health` and `/ready` for smoke checks.
- LLM: http://127.0.0.1:8000/docs

## CI and branch safety

GitHub Actions runs frontend build, backend tests, LLM API tests and deterministic ML tests on `product-transformation`. A green CI run does not prove MongoDB connectivity, local GPU inference, model accuracy or a complete live end-to-end run.

All work is isolated on `product-transformation`. The original `frontend`, `backend`, `AI-model`, `ML_models` and `main` branches are not changed by this restructuring. Do not merge until the branch has been reviewed and the live acceptance flow has been tested.
