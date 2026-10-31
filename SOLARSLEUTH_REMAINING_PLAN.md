# SolarSleuth Remaining Work Plan

## Goal

Make the full SolarSleuth flow reliable and demo-ready:

1. User uploads solar operating data.
2. ML service produces authoritative results.
3. Backend passes bounded evidence to the local LLM.
4. LLM produces a grounded, useful explanation.
5. Frontend presents the result in a polished, Claude/ChatGPT-like experience.
6. Follow-up chat works with the saved analysis.
7. The app runs from the standard local services on ports 8000, 8001, 8002, and 5173.

## Current State

### Working

- ML service contract, validation, energy metrics, expected deviation, anomalies, hypotheses, and evidence.
- Backend orchestration, auth, plant creation, upload, persistence, history, and chat.
- LLM adapter loading through the PEFT venv.
- LLM JSON repair, retry, and response normalization.
- Frontend build passes.
- Isolated E2E passed with:
  - `ml_status="partial"`
  - `expected_deviation_kwh=0.6329557965582353`
  - `llm_status="ready"`
  - `persistence_status="saved"`
  - working chat response
- Tests passed:
  - ML: 86
  - Backend: 24
  - LLM: 10
  - Frontend: `npm run build`

### Not Yet Proven

- Live browser-level flow on standard ports with the updated services.
- LLM output quality comparable to a polished assistant.
- Streaming/conversational chat experience.
- Complete ML analysis for the enriched sample dataset.
- Production/deployment readiness.

### Known Risks / Defects

- Standard services were previously running with system Python. The LLM must run from `llm-service\.venv\Scripts\python.exe`; otherwise `peft` is missing.
- Backend must be restarted after `.env` changes; `--reload` does not reload `.env`.
- LLM is a small local model (Qwen 0.8B) and has a quality ceiling.
- CPU inference is slow (roughly 70-150 seconds per explanation).
- LLM readiness can say `ready` even if the last inference failed.
- Enriched ML run is `partial` because of `unresolved_schema_mapping` and missing forecast.
- Chat currently returns one structured answer, not a streaming conversation.
- No confirmed `production` branch.
- Model weights and secrets must not be committed.

## Execution Order

Execute one task at a time. Do not run the full test suite until the final validation task.

### P0-1: Verify Live Runtime

**Why:** A correct implementation still fails if the live services use the wrong interpreter or stale environment.

**Actions:**
- Confirm port 8000 runs from `llm-service\.venv\Scripts\python.exe`.
- Confirm port 8001 runs from `backend\.venv\Scripts\python.exe`.
- Confirm port 8002 runs the ML service.
- Confirm port 5173 runs the Vite frontend.
- Confirm `backend/.env` has `LLM_TIMEOUT_SECONDS=300`.
- Confirm the shared `INTERNAL_SERVICE_TOKEN` matches across backend, ML, and LLM.
- Confirm CORS includes `http://127.0.0.1:5173` and `http://localhost:5173`.
- Call LLM `/warmup`.
- Call backend `/ready` and confirm `llm_status="ready"`.

**Acceptance:**
- No `ModuleNotFoundError: peft` in LLM logs.
- Backend readiness reports ML reachable, LLM reachable, model loaded, and LLM ready.
- Frontend loads without API errors.

### P0-2: Live End-to-End Check

**Why:** Isolated E2E passed, but the actual standard ports and real database path must work.

**Actions:**
- Register a temporary test user.
- Create a temporary plant.
- Upload `e2e_operating_enriched.csv`.
- Verify upload response contains:
  - ML analysis
  - non-null `expected_deviation_kwh`
  - `llm_status="ready"`
  - `persistence_status="saved"`
- Verify history list and detail.
- Ask one follow-up chat question.
- Open the frontend and verify the analysis, AI sections, history, and chat render correctly.
- Clean up temporary data.

**Acceptance:**
- Full flow succeeds on ports 8001 and 5173.
- No fallback warning unless intentionally triggered.
- Persisted result matches the upload response.

### P0-3: Fix Failures Found During Live E2E

**Why:** Do not build polish on top of an unstable core flow.

**Actions:**
- Fix any live-only errors, timeout issues, CORS failures, auth issues, or serialization problems.
- Add missing error details only where they improve diagnosis.
- Re-run the single failing flow until it passes.

**Acceptance:**
- Live upload, persistence, history, and chat all pass.

### P0-4: Improve LLM Explanation Quality

**Why:** The LLM works, but output must be useful and grounded, not generic.

**Actions:**
- Keep the current strict JSON contract.
- Strengthen the prompt with concrete examples of good observations and evidence.
- Require observations to cite actual ML values.
- Forbid bare key names such as `plant_id`, `ml_results`, or `analysis_status`.
- Keep `possible_causes` empty when evidence is insufficient.
- Ensure `confidence` matches the evidence.
- Add or refine response normalization for bare keys and confidence labels.
- Evaluate three cases:
  - healthy/expected performance
  - clear underperformance
  - partial or missing data
- Consider a larger local model only if time and hardware permit.

**Acceptance:**
- Summary is specific to the supplied ML result.
- Observations include real values.
- No invented measurements, causes, savings, or fault codes.
- Valid JSON on the first attempt or one retry.
- No bare input keys in observations or evidence.

### P1-1: ChatGPT-Like Chat Experience

**Why:** Current chat is a single structured answer; the target experience is conversational.

**Actions:**
- Add streaming responses using SSE or chunked responses.
- Add a message thread with user and assistant messages.
- Render Markdown safely.
- Add typing/loading state.
- Preserve chat history for the current analysis.
- Add suggested follow-up questions.
- Keep answers grounded in the saved analysis and ML result.
- Handle LLM failure without losing the conversation.

**Acceptance:**
- User can ask multiple follow-ups.
- Responses stream into the UI.
- Conversation remains readable and grounded.
- Failure shows a clear retry/fallback message.

### P1-2: Frontend Analysis Polish

**Why:** The result should look like a professional analysis product, not raw JSON.

**Actions:**
- Add strong KPI cards for actual energy, expected energy, and deviation.
- Add an anomaly timeline or severity list.
- Add expandable evidence and hypothesis sections.
- Add confidence and analysis-status badges.
- Add AI status and AI-unavailable banners.
- Add skeleton loaders during upload/analysis.
- Add clear empty, partial, and error states.
- Improve report layout and print/export readability.
- Verify responsive layout and keyboard accessibility.

**Acceptance:**
- A first-time user can understand the result without reading raw fields.
- Partial results are clearly explained.
- AI failure never hides ML results.

### P1-3: ML Completeness

**Why:** The LLM can only be as good as the evidence it receives.

**Actions:**
- Diagnose `unresolved_schema_mapping` on the enriched CSV.
- Expand safe column aliases and mapping rules.
- Confirm timestamp, energy, power, device, and capacity fields are resolved.
- Investigate why forecast energy is unavailable.
- Do not fabricate forecast or energy values.
- Add regression tests for the enriched sample.
- Ensure `expected_deviation` remains numeric when enough evidence exists.

**Acceptance:**
- Enriched sample becomes `full` or has a clear, documented partial reason.
- No unresolved required fields for the demo dataset.
- Expected deviation is present and correctly signed.

### P1-4: Performance and Reliability

**Why:** Slow or failing inference will break the demo experience.

**Actions:**
- Warm the LLM on startup in demo/production mode.
- Show progress or status during long analysis.
- Keep backend LLM timeout at 300 seconds.
- Add a queue or concurrency guard for uploads.
- Cache repeated analysis/explanation requests where safe.
- Surface last inference error in readiness or UI.
- Verify retry behavior and fallback.
- Consider GPU inference if available.

**Acceptance:**
- Upload completes within the configured timeout.
- UI never appears frozen.
- Failures are visible and recoverable.

### P2-1: Deployment and Final Validation

**Why:** The local demo must be reproducible.

**Actions:**
- Confirm the intended production branch.
- Verify `.env.example` files are complete.
- Confirm secrets are not committed.
- Confirm model weights are excluded from git.
- Document startup commands and ports.
- Build the frontend.
- Run one short final regression pass:
  - ML tests
  - Backend tests
  - LLM tests
  - Frontend build
  - One live upload/chat smoke test
- Prepare a demo checklist.

**Acceptance:**
- Clean checkout can be started from documented commands.
- All short tests pass.
- Demo flow works end to end.

## Suggested Immediate Sequence

1. Verify live runtime and warm the LLM.
2. Run live E2E on standard ports.
3. Fix only what fails.
4. Improve LLM explanation quality.
5. Add streaming chat UX.
6. Polish the frontend.
7. Fix ML partial-analysis gaps.
8. Add performance/reliability safeguards.
9. Final short regression and deployment check.

## Definition of Done

- Standard services run with the correct interpreters.
- Upload produces ML results, a grounded LLM explanation, and a saved history record.
- Frontend shows a polished analysis with clear status, KPIs, evidence, and limitations.
- Chat supports multiple grounded follow-ups with a conversational UI.
- Partial or failed AI output never hides ML results.
- The demo dataset produces useful, non-generic output.
- All short regression checks pass.
- No secrets or model weights are committed.

## Execution Update — 2026-10-31

### Implemented on `product-transformation`

- [x] LLM inference now makes one corrective retry with the original evidence and an explicit JSON contract.
- [x] LLM response normalization repairs common small-model shape errors, fills safe defaults, and preserves strict response validation.
- [x] LLM readiness now distinguishes model loading from the last inference failure; backend readiness exposes the downstream model name and inference error.
- [x] Follow-up chat falls back to a clearly labelled deterministic answer assembled only from the saved ML report when local LLM inference is unavailable. The fallback does not invent causes or measurements and is persisted in chat history.
- [x] Initial upload also returns an evidence-only deterministic explanation if the local LLM is unavailable or its response cannot be validated; the ML report is preserved.
- [x] Added opt-in / production startup warmup for the local LLM and a warmup endpoint; the default development behavior remains configurable.
- [x] Older backend deployments without the streaming route are handled by a non-streaming chat fallback.
- [x] Fixed the ML output-schema regression: `expected_deviation` and `expected_deviation_kwh` were required by the contract but missing from its `properties`, causing 19 deterministic-ML tests to fail.
- [x] Exposed optional weather, forecast, device and event-log files through the frontend, backend and ML API. The Python pipeline receives a named temporary input directory; single-file uploads remain supported.
- [x] Waterfall unavailability now identifies the exact missing energy component and reason.
- [x] Added regression coverage for the supplied `solar_plant_30day_stress.csv` headers and the correct no-forecast behavior.

### Verification

- [x] A full CI run passed all four jobs (deterministic ML, backend, LLM API and frontend) after the schema, multi-file upload and UI changes.
- [x] The stress-dataset and actionable-waterfall regression tests passed in the subsequent full CI run.
- [x] Full CI passed all four jobs on the startup-warmup changes. On the latest fallback-label change, backend, LLM API and frontend jobs passed; the deterministic-ML job was still running when this note was updated.

### Still requires the user's live environment

- [ ] Verify the four local services and their interpreters on ports 8000, 8001, 8002 and 5173.
- [ ] Warm the actual local model and verify the shared service token and CORS settings.
- [ ] Run the real browser upload, persistence, history and follow-up flow against the user's database.
- [ ] Upload a separate forecast file to make forecast-relative waterfall reconciliation available. The supplied stress CSV has actual energy and baseline inputs but no forecast column; forecast values must not be fabricated.
- [ ] Evaluate LLM explanation quality on healthy, underperforming and partial-data cases.
- [ ] Complete remaining frontend polish, performance checks and deployment validation.

Live browser/runtime validation cannot be claimed from repository CI alone; it must be completed against the running local services.
