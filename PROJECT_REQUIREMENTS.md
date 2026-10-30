# SolarSleuth — Product, Architecture & Engineering Requirements

> **Purpose:** This document is the implementation contract for the SolarSleuth solar-plant performance intelligence application. It reflects the agreed user workflow and architecture. A requirement is not considered complete until it is implemented and verified by tests.

## 1. Product objective

SolarSleuth ingests solar-plant data from CSV and Excel files, validates and maps the supplied measurements, runs deterministic analysis, and asks a locally hosted language model to explain the computed evidence in clear, detailed language.

The application must be evidence-led:
- Uploaded files are the only source of plant measurements.
- No hard-coded sample plant readings, fabricated telemetry, or manual measurement-entry workflow may appear in the operational application.
- The ML service is the authority for numerical calculations, anomaly detection, attribution, and energy variance.
- The LLM is an explanation and conversation layer. It must never invent, recalculate, or silently modify ML values.
- Unknown or unsupported information must be labelled as unknown, not guessed.

## 2. User experience and navigation

Keep the workspace navigation intentionally small:
1. **Overview** — service health, latest uploaded dataset, latest analysis status and key metrics from the most recent successful ML result.
2. **Upload & analyse** — upload CSV/XLSX, review detected columns/units and validation findings, choose supported analysis options, and start processing.
3. **Reports** — view the complete report for a successful analysis and export/print it.
4. **AI explanation** — read the long-form explanation and, when the conversation API is implemented, ask follow-up questions grounded in the same uploaded dataset and ML result.

Do not expose separate sidebar destinations for individual diagnostic sub-features such as variance, cause classification, validation lab, or methodology. Present those as sections within the analysis/report where useful.

### Visual and interaction requirements
- Professional, responsive dashboard; clear hierarchy, restrained colour, accessible contrast.
- Use subtle transitions for page changes, loading states, streamed/appearing explanation sections, and report sections. Respect `prefers-reduced-motion`.
- Use emojis sparingly as visual signposts, not as substitutes for technical detail.
- The AI response should read naturally, with a concise executive summary followed by detailed sections, evidence, uncertainty, and actionable checks.
- Provide loading, empty, partial-result, validation-error, timeout, service-unavailable, and retry states.
- Never display placeholder metrics as if they came from a plant.

## 3. Data ingestion — file-only workflow

### Supported initial upload contract
- CSV and XLSX files.
- Upload one operating-data file through the current HTTP integration.
- Enforce a configurable size limit (currently 25 MiB).
- Support optional plant identifier, analysis mode, timezone, sampling interval, and Excel worksheet name.
- Do not add manual entry of power, irradiance, temperature, capacity, or other measurements.

### Required ingestion pipeline
1. Receive file through the application backend.
2. Check extension, content type/signature where feasible, size, filename safety, and parser limits.
3. Store only in a random temporary location; never trust a client-supplied path.
4. Pass the file to the deterministic ML service.
5. Parse the file and inspect headers, rows, timestamps, missing values, duplicate records, numeric types, and candidate units.
6. Map supported column aliases to canonical fields using explicit, auditable mapping rules.
7. Infer units only when the evidence is unambiguous (header/unit metadata or documented conversion rule). Otherwise mark the unit as unknown and request clarification or return a partial result.
8. Validate physical ranges, timestamps, timezone consistency, interval consistency, impossible values, and schema conflicts.
9. Report mapped columns, inferred units, unmapped columns, warnings, rejected rows, and assumptions in the response.
10. Delete temporary files in a guaranteed cleanup path, including failures and timeouts.

### Column mapping and unit safety
- Mapping must be based on the ML service's schema registry/alias rules, not frontend heuristics.
- Preserve original column names and record the canonical mapping.
- Do not silently convert ambiguous units. For example, do not assume whether a power column is W or kW based only on numeric magnitude.
- Every conversion must identify source unit, target unit, and conversion rule.
- If required fields cannot be mapped safely, return a structured validation error or partial analysis with explicit limitations.
- Unknown columns must be preserved in ingestion metadata and reported, not silently treated as useful model inputs.
- Excel workbooks with multiple plausible sheets need explicit sheet selection or a clear deterministic default with the selected sheet reported.

### Multi-file future extension
The Python pipeline may support operating, weather, device, forecast, event-log, and metadata inputs. The current HTTP adapter accepts only one operating-data file. Do not claim multi-file ingestion until backend and ML API contracts, upload UI, validation, tests, and report provenance support it end-to-end.

## 4. Service architecture and request flow

All four services must be independently runnable and connected through explicit health-checked APIs.

| Service | Local port | Responsibility |
|---|---:|---|
| React/Vite frontend | 5173 | File selection, upload, progress, results, report and AI explanation UI |
| Application backend | 8001 | Browser-facing API, validation, orchestration, service authentication, response contract |
| Deterministic ML API | 8002 | File ingestion, schema mapping, validation, calculations, anomalies, evidence and metrics |
| Local LLM API | 8000 | Explain ML output and answer grounded follow-up questions |

### Required sequence
1. Browser sends the file only to the application backend.
2. Backend validates request metadata and upload constraints.
3. Backend forwards the file and permitted options to ML service.
4. ML service returns a structured deterministic result.
5. Backend validates the ML response and rejects invalid/failed analysis before calling the LLM.
6. Backend sends a compact, bounded ML evidence payload—not the raw uploaded dataset—to the local LLM.
7. LLM returns a structured explanation grounded in that payload.
8. Backend validates the LLM response and returns both the unchanged ML result and explanation to the frontend.
9. Frontend renders the ML facts separately from the AI narrative.

The frontend must never call ML or LLM services directly. The backend must not perform plant-energy arithmetic. The LLM must not be the source of calculated values.

## 5. Deterministic ML contract

The ML response should include, where available:
- Analysis status: success, partial, invalid input, or failed.
- Dataset/plant identifier and analysis mode.
- Row counts, timestamp coverage, detected interval, selected worksheet.
- Data-quality status, validation warnings/errors, rejected-row counts.
- Original-to-canonical column mapping and units.
- Expected/forecast/actual energy and deviation, with explicit units and provenance.
- Energy waterfall and component contributions.
- Detected anomalies and supporting evidence.
- Attribution hypotheses with evidence and uncertainty.
- Unresolved fields and limitations.

Numerical fields must retain their values and units through backend and frontend. Missing values remain null/unknown; never replace them with zero or a guessed estimate.

## 6. Local LLM behaviour

The local LLM is responsible for explanation, not deterministic analysis.

### Response style
Aim for the clarity, structure, conversational usefulness, and depth associated with polished assistants such as ChatGPT or Claude, while remaining truthful about the model's actual capability and local hardware limits. Do not promise identical quality or unrestricted capabilities.

A successful explanation should normally contain:
1. **Executive summary** — what happened and how material the deviation is, if supported.
2. **What the data shows** — explain ML metrics without changing them.
3. **Variance breakdown** — explain the ML energy waterfall and contributions.
4. **Likely contributing factors** — distinguish ranked hypotheses from confirmed causes.
5. **Evidence** — cite specific returned metrics, anomalies, timestamps, and mapped fields.
6. **Recommended checks** — practical technician/operator checks ordered by priority.
7. **What is still unknown** — missing data, ambiguity, and limitations.
8. **Confidence** — only use the ML/LLM contract's supported confidence semantics and explain why.

### Guardrails
- Never invent plant readings, timestamps, faults, savings, financial impact, or causal certainty.
- Never recompute or modify numerical values from ML.
- Refer to missing evidence explicitly.
- Distinguish observation, hypothesis, and recommendation.
- If the ML status is partial, explain what could and could not be concluded.
- Return machine-valid structured output and handle generation truncation/errors.
- Keep inference local; no third-party model API is part of the intended flow.

### Follow-up chat
A real chat experience requires a backend conversation endpoint that receives the conversation history plus the original validated ML result, applies size limits, authenticates the caller, and forwards only the bounded evidence/context to the local LLM. Until that endpoint exists, the frontend must not pretend that arbitrary follow-up questions are being answered against the uploaded dataset. A chat-like presentation alone is not a functioning chat system.

## 7. Reports

A report must be generated from the actual successful or explicitly partial analysis response—never static sample content.

Required report sections:
- Report title, generation timestamp, dataset filename (sanitized), plant identifier if provided, analysis status.
- Dataset profile and time coverage.
- Detected columns, canonical mappings, units, and unresolved columns.
- Data validation summary, warnings, rejected rows, and assumptions.
- Key ML metrics with units and provenance.
- Energy waterfall and anomaly/evidence details.
- Long-form LLM explanation, hypotheses, recommended checks, confidence, and limitations.
- Clear disclaimer that hypotheses require operational verification.

Export/print must include all relevant sections, readable page breaks, and no navigation/sidebar controls. A report must be unavailable or clearly marked incomplete when analysis fails. PDF download should be added only when a reliable report-generation implementation is available; browser print-to-PDF is an acceptable initial export path.

## 8. Security and resilience requirements

### Network and service security
- Bind local development services to loopback unless intentionally deployed behind a secured private network.
- Backend is the only public/browser-facing service.
- Require a high-entropy shared service token for backend-to-ML and backend-to-LLM calls outside local development. Compare tokens safely and never log them.
- Production mode must fail closed if required secrets are absent.
- Restrict CORS to explicit trusted frontend origins.
- Use HTTPS and private networking for remote deployments.
- Do not expose service tokens, model paths, stack traces, internal URLs, or raw exception details to the browser.

### Upload and API hardening
- Enforce file size, extension, content/signature, parser, row/column, and processing-time limits.
- Sanitize display filenames; generate server-side temporary names.
- Protect against path traversal, malformed workbooks, decompression/resource exhaustion, and oversized cells/rows.
- Use request timeouts, bounded concurrency, and clear 4xx/5xx responses.
- Clean temporary files on success, exception, cancellation, and timeout.
- Avoid logging raw plant data or sensitive workbook contents.
- Validate response schemas from ML and LLM before returning them.
- Add rate limiting and real server-side user authentication/authorization before production use.
- Do not treat browser-local demo login or localStorage as security controls.
- Apply dependency pinning/scanning and keep secrets out of Git.

### Failure isolation
- If ML is unavailable, fail the analysis cleanly; do not call the LLM with fabricated data.
- If ML returns invalid input, show validation details and do not call the LLM.
- If ML returns partial results, pass only valid evidence and limitations to the LLM.
- If LLM is unavailable, preserve and show the valid ML result with a clear explanation-unavailable state.
- Retry only safe transient operations with bounded attempts; avoid duplicate processing.
- Health/readiness endpoints must distinguish process health from model/pipeline readiness.
- Frontend must show which service failed without exposing internal implementation details.

## 9. Frontend implementation requirements

- Remove manual measurement forms and all static/demo plant metrics from the operational workspace.
- Reduce sidebar to Overview, Upload & analyse, Reports, and AI explanation.
- Display upload progress and distinct pipeline stages: Upload → Validate/map → ML analysis → AI explanation → Report ready.
- Render ML metrics and AI explanation in separate sections.
- Render structured values using their source units; do not infer units in React.
- Use responsive charts only when the ML response includes valid numeric series.
- Provide report print/save support based on the current result.
- Use subtle animations and accessible reduced-motion behaviour.
- Escape/render uploaded filenames and model text safely as text; never inject model output as HTML.
- Preserve the existing theme option if it remains accessible and consistent.

## 10. Verification and acceptance criteria

Do not mark the project complete based on successful server startup alone.

### Automated tests
- ML: supported CSV/XLSX ingestion, aliases, units, unknown columns, missing values, duplicates, invalid timestamps, invalid units, partial/invalid status, temp cleanup.
- Backend: upload limits, auth, ML-before-LLM ordering, no LLM call on invalid ML result, partial-result handling, LLM outage fallback, safe error responses, timeout behaviour.
- LLM: prompt guardrails, schema validation, numeric-value preservation, no invented evidence, truncation/error handling.
- Frontend: no manual measurement path, four-item navigation, upload validation, loading/error/partial states, report output, no static plant metrics.
- End-to-end: upload representative CSV and XLSX fixtures and verify the complete frontend → backend → ML → LLM → backend → frontend path.

### Manual acceptance
- Test files with different valid header names and units.
- Confirm mappings and unit conversions in the report.
- Confirm ambiguous units cause warnings/clarification rather than silent assumptions.
- Stop each service independently and verify graceful failure behaviour.
- Confirm the browser communicates only with port 8001.
- Confirm the same ML numeric values appear unchanged in the final report.
- Verify report print layout and reduced-motion accessibility.

## 11. Current integration boundaries to keep visible

The current integration baseline has a single operating-data CSV/XLSX upload path. Multi-file context uploads and a grounded follow-up chat API are not yet part of that contract. Browser-local demo authentication is not production authentication. Real-world reliability, arbitrary-file compatibility, and polished LLM quality must be demonstrated with tests and representative datasets; they must not be claimed in advance.

## 12. Definition of done

The project is done only when all four services connect reliably, file ingestion and schema/unit mapping are validated, deterministic ML calculations are traceable, the local LLM produces grounded explanations, reports reflect actual uploaded data, failure paths are safe, security controls are verified, and the automated plus end-to-end acceptance tests pass.
