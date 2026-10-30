# SolarSleuth integration workspace

This branch assembles the existing workstreams without rewriting their source code.

## Source snapshots

| Component | Original branch | Source commit |
|---|---|---|
| Frontend | `frontend` | `916f32f7d2ffa73eb1a4171bfe5b6be3a7dfd6d2` |
| Application API | `backend` | `327662d84feaf52dd514b32670c7ba403db8abc1` |
| Local LLM API | `AI-model` | `274968381343a16462946669ee3745aa1ab0ce6d` |
| Deterministic ML | `ML_models` | `6a899f13e29e37f0457640f290f41444b91fb953` |

The service snapshots are stored under `services/` so their root-level files, configuration, tests and instructions do not collide with the frontend. The original workstream branches are unchanged.

## Service map

| Component | Directory | Port |
|---|---|---:|
| Frontend | repository root | 5173 |
| Application backend | `services/backend` | 8001 |
| Local LLM API | `services/llm` | 8000 |
| Deterministic ML API | `services/ml` | 8002 |

The browser must continue to call only the application backend. The backend remains responsible for upload validation, ML-first orchestration and the LLM fallback path. ML remains the numerical authority; the LLM remains explanation-only.

## Local startup (PowerShell)

Install frontend dependencies once:

```powershell
npm install
```

Start each service in its own terminal.

**Terminal 1 — deterministic ML**

```powershell
cd services/ml
py -3.11 -m venv .venv-ml
.\.venv-ml\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8002
```

**Terminal 2 — local LLM API**

```powershell
cd services/llm
py -3.11 -m venv .venv-llm
.\.venv-llm\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-api.txt
Copy-Item .env.example .env
```

Place the trained adapter directory at `services/llm/models/solar-qwen-lora-final`, or set `ADAPTER_PATH` in the local `.env`. Model weights are intentionally not committed. Then run:

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Install the CUDA-enabled PyTorch build appropriate to the machine before running inference if GPU inference is required; follow the LLM workstream's `README_LOCAL_API.md`.

**Terminal 3 — application backend**

```powershell
cd services/backend
py -3.11 -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Before starting the backend, edit `services/backend/.env` locally:

- Set `MONGODB_URI` to your MongoDB Atlas connection string.
- Keep `MONGODB_DATABASE=solarsleuth` unless you want another database name.
- Set `JWT_SECRET` to a fresh random secret (at least 32 characters). Generate one with:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

- Configure the same high-entropy `INTERNAL_SERVICE_TOKEN` in the backend, ML and LLM `.env` files.
- Keep `MONGODB_URI`, `JWT_SECRET`, `API_ACCESS_TOKEN` and `INTERNAL_SERVICE_TOKEN` private. Never put them in frontend variables or commit local `.env` files.

Then start the backend:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

The backend creates unique email, plant identifier, and analysis request indexes in MongoDB. Registration stores a password hash and a separate business workspace ID for each account. Login returns a signed, expiring bearer token. The upload endpoint requires that token. Successful validated ML analyses (including the deterministic fallback when the LLM is unavailable) are stored with business ownership and report metadata; raw uploaded file bytes are not stored. The authenticated plant directory uses `GET /api/v1/plants`, `POST /api/v1/plants`, and `PATCH /api/v1/plants/{plant_id}`; identifiers are unique within a business workspace. The frontend provides a Plant directory page and lets users select a registered plant for new uploads. Existing free-text plant IDs remain accepted for backward compatibility. The authenticated history endpoints are `GET /api/v1/analyses?limit=20&offset=0` and `GET /api/v1/analyses/{request_id}`. History can be filtered to a single plant with `GET /api/v1/analyses?plant_id={plant_id}`; the filter remains business-scoped and uses a compound index for efficient retrieval. Follow-up chat uses `GET /api/v1/analyses/{request_id}/chat` and `POST /api/v1/analyses/{request_id}/chat` with JSON `{"question":"..." }`. All report and chat queries enforce business-workspace scoping. If MongoDB is not configured in development, the backend still starts for health checks, but registration/login and account-backed persistence fail closed with HTTP 503.

**Terminal 4 — frontend**

```powershell
npm run dev
```

Open `http://127.0.0.1:5173`.

## Regression checks

Run each suite from its service directory:

```powershell
# Frontend, from repository root
npm run build

# Application backend
cd services/backend
python -m pytest -q

# Local LLM API (lightweight API tests; no model weights required)
cd ../llm
python -m pip install pytest
python -m pytest -q tests

# Deterministic ML
cd ../ml
python -m pytest -q
```

## Existing limitations (not silently changed by integration)

- The browser-facing upload contract accepts one operating-data CSV/XLSX file, up to the configured limit. Do not imply separate weather/device/forecast/event-log uploads are exposed.
- MongoDB-backed registration/login, JWT authorization, business-scoped plant directory CRUD (create/list/update), and business-scoped persistent analysis history are implemented on the integration branch. The frontend restores the latest 100 reports after authentication; list pagination is available through the backend API.
- The AI explanation workspace supports follow-up questions against a selected saved analysis. The backend retrieves the report using the authenticated business scope, supplies only bounded deterministic ML evidence and recent conversation context to the local LLM, and stores the user/assistant messages in MongoDB. The LLM response uses the existing strict explanation schema; the saved ML result is never modified. The chat is report-grounded, not a general-purpose chatbot.
- The trained model adapter is a local artifact and is not included in Git.
- A successful CI run proves the relevant automated tests/build pass; it does not prove real-world model accuracy or full local GPU inference.

## Change-safety rules

1. Do not edit the source snapshots in this integration step.
2. Do not alter the ML result schema, ML calculations, upload endpoint contract, LLM prompt/schema, or service-token checks as part of frontend/product work.
3. Any future change must be incremental and tested against the regression checks above.
4. Keep the original workstream branches intact. Integrate changes through reviewable commits and pull requests.
