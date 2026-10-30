# SolarSleuth — Solar Recovery Intelligence

SolarSleuth helps solar-plant operators investigate generation variance using deterministic calculations and evidence-aware explanations.

## Connected local architecture

| Component | Branch | Port | Responsibility |
|---|---|---:|---|
| React + Vite frontend | `frontend` | 5173 | CSV/XLSX upload, existing manual readings, animated UI, renders both outputs |
| Application backend | `backend` | 8001 | Request validation, upload handling, orchestration, internal service authentication |
| Deterministic ML service | `ML_models` | 8002 | Ingestion, schema mapping, validation, physics baseline, anomaly detection, attribution and energy waterfall |
| Local LLM API | `AI-model` | 8000 | Explanation only: summary, possible causes, evidence, technician checks and limitations |

### Upload data flow

1. The frontend sends one operating-data CSV/XLSX file to `POST http://127.0.0.1:8001/api/v1/analyze/upload`.
2. The backend validates file type/size and forwards the file to `POST http://127.0.0.1:8002/api/v1/analyze`.
3. The ML service calls the existing `src.pipeline.run_pipeline` and returns the versioned contract-v2 result. It owns all calculations.
4. The backend passes the full ML result as `ml_results` to `POST http://127.0.0.1:8000/api/v1/analyze`.
5. The local LLM explains the supplied contract without recalculating values.
6. The backend returns `ml_analysis` and `analysis` together to the frontend.

The existing manual input path remains available at `POST /api/v1/analyze`. The frontend login remains a browser-local demo gate, not production authentication.

## Running all services on Windows

Because each component lives on its own branch, use separate working directories (Git worktrees are convenient) so the branches can run simultaneously. From a clone with the five branches fetched:

```powershell
git fetch origin
git worktree add ..\solarsleuth-frontend frontend
git worktree add ..\solarsleuth-backend backend
git worktree add ..\solarsleuth-ml ML_models
git worktree add ..\solarsleuth-ai AI-model
```

Open four PowerShell terminals:

**Terminal 1 — ML service (8002)**

```powershell
cd ..\solarsleuth-ml\ML-models
py -m venv .venv-ml
.\.venv-ml\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8002
```

**Terminal 2 — local LLM (8000)**

```powershell
cd ..\solarsleuth-ai
py -m venv .venv-ai
.\.venv-ai\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

**Terminal 3 — backend (8001)**

```powershell
cd ..\solarsleuth-backend
py -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

**Terminal 4 — frontend (5173)**

```powershell
cd ..\solarsleuth-frontend
npm install
npm run dev
```

Set the same high-entropy `INTERNAL_SERVICE_TOKEN` in the ML, backend and AI `.env` files. For local development, all three may be left empty. Do not set `ENVIRONMENT=production` without configuring the shared token. Keep services bound to loopback for the local prototype.

The LLM service requires a compatible local base model and adapter. Verify `ADAPTER_PATH` exists and contains `adapter_config.json`; the repository does not contain model weights.

## Current integration scope and limitations

- The HTTP adapter currently accepts one operating-data CSV/XLSX file. The Python ML pipeline supports richer scenario/mapping inputs, but the web upload does not yet expose separate weather, device, forecast or event-log files.
- ML outputs can be `partial`; missing evidence remains unavailable and is passed to the LLM as a limitation.
- The LLM is not allowed to calculate or change numerical metrics.
- Multi-service code has been committed to each component branch, but runtime tests/builds must still be executed locally. A mocked API test is not proof that the local model loads or that a real plant file is correctly interpreted.
- The frontend demo authentication is not real server-side authentication. Public deployment needs real auth, HTTPS/private networking, rate limiting and managed secrets.

## Branch responsibilities

- `main`: shared architecture and runbook.
- `frontend`: React/Vite UI.
- `backend`: API and orchestration.
- `ML_models`: deterministic pipeline and private HTTP adapter.
- `AI-model`: local explanation API and model wrapper.

## Evidence-first rules

Never fabricate measurements or turn hypotheses into confirmed faults. Keep observed data, deterministic calculations, model outputs and unresolved evidence distinct. Do not present synthetic test metrics as real-world accuracy.
