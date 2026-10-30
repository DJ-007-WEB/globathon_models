# Integration baseline and invariants

This branch combines four independently testable services under dedicated top-level directories. The source workstreams remain isolated on their original branches.

## Service map

| Service | Directory | Port | Responsibility |
|---|---|---:|---|
| Frontend | `frontend/` | 5173 | React/Vite UI; browser calls backend only |
| Backend | `backend/` | 8001 | Auth, MongoDB persistence, upload validation, orchestration |
| Deterministic ML | `ml-service/` | 8002 | Parsing, validation, numerical energy analysis |
| Local LLM | `llm-service/` | 8000 | Evidence-grounded explanation only |

## Source snapshots

| Component | Original branch | Source commit |
|---|---|---|
| Frontend | `frontend` | `916f32f7d2ffa73eb1a4171bfe5b6be3a7dfd6d2` |
| Backend | `backend` | `327662d84feaf52dd514b32670c7ba403db8abc1` |
| Local LLM | `AI-model` | `274968381343a16462946669ee3745aa1ab0ce6d` |
| Deterministic ML | `ML_models` | `6a899f13e29e37f0457640f290f41444b91fb953` |

## Non-negotiable contracts

1. The browser calls only the backend.
2. Backend invokes deterministic ML first; only validated bounded evidence is sent to LLM.
3. ML is the sole numerical authority. LLM must not calculate or mutate metrics.
4. Existing upload contract remains one CSV/XLSX file up to configured limit.
5. Internal service token is shared only among backend, ML and LLM; never expose it to frontend.
6. MongoDB data is scoped by authenticated `business_id`; raw upload bytes are not persisted.
7. Model weights/LoRA adapter remain local artifacts and are not committed.
8. Original workstream branches are not modified by this integration branch.

## Current product capabilities

- MongoDB-backed account registration/login with Argon2 password hashes and expiring JWTs.
- Business-scoped plant directory (create/list/update API; UI supports registration and plant selection).
- CSV/XLSX upload and ML-first analysis orchestration.
- Saved analysis history and detail retrieval, business scoped; optional plant filter is indexed.
- Validation Lab, report views and report-grounded follow-up chat with persisted conversation.
- Explicit ML fallback behavior when LLM is unavailable.

## Known limitations

- No password reset/email verification or production-grade rate limiting.
- No plant deletion UI/API; avoid destructive deletion of plants with report history.
- No live inference guarantee without installing the local model and complete PEFT adapter.
- A passing automated suite does not prove MongoDB Atlas credentials, local GPU compatibility, model quality or live full-stack operation.
- Upload endpoint does not expose separate weather/device/forecast/event-log files.
- Plant dashboard visualizations/report comparison must only use metrics present in the deterministic ML result; never fabricate missing values.

## Local setup and tests

Follow the root [README](README.md) for exact Windows PowerShell commands, environment configuration, service health checks, individual tests and the end-to-end acceptance checklist.

## Change safety

Do not modify ML calculations, ML response schema, upload endpoint contract, LLM prompt/schema, or service-token checks as part of UI/product changes unless a separate reviewed task explicitly requires it. Keep each change incremental and run all four CI jobs before declaring the branch green.
