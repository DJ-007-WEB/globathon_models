# PROJECT_REQUIREMENTS.md compliance check — 2026-10-31

Checked against `PROJECT_REQUIREMENTS.md` on `product-transformation` after the second execution pass of
`SOLARSLEUTH_REMAINING_PLAN.md`. Evidence: unit suites (ML 93, backend 35, LLM 20, frontend build) and the
live harness in `scripts/e2e/` (real ML/backend/frontend on 8000–8002/5173, in-memory MongoDB, scripted LLM output).

Legend: ✅ met · ⚠️ partially met · ❌ not met · 🔒 needs the developer's environment to prove

| § | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 1 | File-only, no fabricated readings; ML is numeric authority | ✅ | No manual-entry endpoint (test); LLM grounding guard removes statements with measurements absent from ML output |
| 2 | Four-item navigation | ✅ | Overview, Upload & analyse, Reports, AI explanation; plants and validation detail are sub-views (browser run) |
| 2 | Loading/empty/partial/validation/timeout/unavailable/retry states | ✅ | Pipeline stepper, skeletons, partial note, 429/timeout messages, AI-unavailable banner, chat retry |
| 2 | Reduced motion | ✅ | `prefers-reduced-motion` rules cover new animations |
| 3 | CSV/XLSX, 25 MiB limit, options | ✅ | **XLSX was previously rejected for every upload** — fixed with regression test |
| 3 | Mapping via ML registry; report mapped/unmapped columns, units, conversions | ✅ | New `column_mapping` contract section rendered in the report |
| 3 | Parser row/column and decompression limits | ✅ | `MAX_ROWS`, `MAX_COLUMNS`, `MAX_XLSX_UNCOMPRESSED_BYTES` at the ML boundary |
| 3 | Ambiguous units not silently converted | ✅ | Existing ML tests (`test_t07_unit_conversion_is_explicit`, schema-mapping tests) |
| 3 | Temp files cleaned on success and failure | ✅ | Existing ML API tests |
| 3 | Multi-file inputs end-to-end | ✅ | Operating + weather + forecast + devices verified live; per-input mapping provenance in the report |
| 4 | Browser talks only to backend; ML before LLM; no LLM call on invalid/failed ML | ✅ | Browser request hosts = 5173, 8001, Google Fonts; ML-down upload → 503 with no LLM call |
| 5 | ML contract fields, nulls stay null | ✅ | Contract schema validation; "Not reported" in UI, never 0 |
| 6 | Grounded explanation, hypotheses vs confirmed causes, confidence semantics | ✅ | Grounding guard + tests; causes cleared without ML findings; "confirmed" wording hedged; confidence capped on partial/failed quality |
| 6 | Long-form sections incl. explicit "variance breakdown" | ⚠️ | Response schema has summary, observations, causes, evidence, checks, limitations, confidence; no dedicated variance-breakdown field (the report's ML waterfall section covers it) |
| 6 | Real model quality | 🔒 | No adapter/weights in this environment; evaluate on healthy / underperforming / partial datasets |
| 6 | Follow-up chat with history, auth, size limits | ✅ | Streamed + non-streamed, 8-turn bounded context, 2 000-char limit, persisted per report |
| 7 | Report sections, print/export, disclaimer | ✅ | Mapping, validation, metrics, waterfall, anomalies, AI explanation, disclaimer; print CSS hides navigation |
| 8 | Token comparison, production fails closed, CORS allow-list | ✅ | `hmac.compare_digest`; startup errors without secrets in production; CORS verified live |
| 8 | No internal details to browser | ✅ | Production `/ready` now hides raw LLM error text and model paths |
| 8 | Rate limiting | ❌ | Only concurrency guards (429). Add rate limiting before public deployment |
| 8 | Server-side auth (not localStorage) | ⚠️ | JWT + Argon2 server-side; the token is kept in `localStorage` (XSS exposure). No password reset or email verification |
| 9 | Safe rendering of filenames/model text | ✅ | React text nodes only; no `dangerouslySetInnerHTML` |
| 10 | Automated tests per service | ⚠️ | ML/backend/LLM covered. Frontend has only `tsc` + build in CI; the browser E2E script is not in CI |
| 10 | Manual acceptance on real services | 🔒 | Run `scripts/verify-local-runtime.ps1` with the real model and MongoDB |
| 12 | Definition of done | ⚠️ | Blocked on the 🔒 items, rate limiting, and frontend tests in CI |
