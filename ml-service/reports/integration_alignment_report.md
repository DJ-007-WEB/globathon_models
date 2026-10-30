# Integration Alignment Report

**Project:** SolarSleuth / Solar Recovery Intelligence — ML pipeline
**Document reviewed:** `Integration.docx` — *ML Integration Handoff* (P0/P1/P2 checklist, proposed contract, T01–T12 test cases)
**Repository:** `ML-models`
**Branch / commit reviewed:** `ML_models` / `b391608` (*Add local model adapter contract*)
**Review date:** 2026-10-30
**Method:** static review of every pipeline module plus executed end-to-end scenarios, negative cases and the existing test suite.

---

## 1. Executive verdict

**The ML pipeline is not integration-ready yet.**

The individual analytical modules are substantially better than the integration document assumes: ingestion, schema mapping, validation, physics baseline, anomaly detection, attribution and waterfall arithmetic are all implemented and unit-tested. **However, the actual end-to-end entry point bypasses most of them and currently produces misleading energy values.**

The most serious issue is not a missing feature — it is that the shipped sample scenario returns:

- `analysis_status = "ok"`
- `waterfall.status = "ok"`
- `expected_energy_kwh = 0.0`
- `weather_effect_kwh = -5282.33`
- while the same output’s `limitations` says *“AC capacity is unavailable; expected power is unavailable.”*

That is exactly the kind of contradictory, evidence-free result the integration document is designed to prevent. The LLM layer would be asked to explain numbers the ML layer did not actually calculate.

### 1.1 Scorecard against the integration document

| Integration area | Status | Short reason |
|---|---|---|
| P0 — Single callable end-to-end entry point | **Partial** | Python function + CLI exist, but only for a directory of canonical CSV filenames. |
| P0 — CSV and Excel accepted by the real entry point | **Fail** | `run_pipeline()` reads CSV directly; Excel is not accepted. |
| P0 — Canonical input schema published | **Fail** | No required/optional field table, units, aliases or timestamp semantics are published. |
| P0 — Stable output contract and schema version | **Partial** | Fields exist, but units, timezone, interval range and enums are missing; schema is permissive. |
| P0 — Status semantics | **Fail** | Uses `ok/warning/unavailable`, not the agreed `success/partial/invalid_input/failed`; can report `ok` when the baseline is unavailable. |
| P0 — Reproducibility identifiers | **Partial** | Hardcoded `model_version`/`mapping_version`; no config hash, vocab version, seed or model artifact identifier in output. |
| P1 — Forecast vs baseline vs actual kept distinct | **Fail** | Forecast falls back to baseline; expected energy falls back to actual. |
| P1 — Power/energy conversion uses actual interval | **Fail** | Defaults to 60 minutes when duration is unknown; 15-minute data is overstated 4×. |
| P1 — Time-series integrity | **Partial** | Strong checks exist in `validation.py`, but the pipeline calls only the lightweight `validate_frame()` and discards the report. |
| P1 — Missing/conflicting data surfaced | **Fail** | Missing required fields are not listed as unresolved; NaNs are silently skipped in totals. |
| P1 — Anomaly minimum history documented | **Partial** | Peer/CUSUM thresholds exist in config, but minimum history is not stated in the output contract. |
| P1 — Attribution separates facts/hypotheses/causes | **Partial** | Good discipline in `attribution.py`, but confidence is a hardcoded constant and every interval emits a hypothesis. |
| P1 — Waterfall reconciles and avoids double counting | **Fail in E2E** | Arithmetic unit tests pass; the pipeline feeds it a fabricated `E = 0`, so reconciliation is meaningless. |
| P1 — Confidence defined | **Fail** | Fixed values `0.85 / 0.60 / 0.15` by status; no calculation or calibration. |
| P2 — Environment/run documentation | **Partial** | README has a Windows quick start, but hardcodes `D:\Storage\Downloads\...`, omits Python version and pytest command. |
| P2 — Runtime/memory measured | **Not done** | No runtime or memory measurement in the repository. |
| P2 — Actionable errors, no raw tracebacks | **Fail** | Empty file, missing path and alias-header cases raise raw exceptions. |
| P2 — Upload validation / cleanup | **Partial** | Ingestion validates extension and encoding, but is not wired into the pipeline and does no size/sheet-selection policy. |
| P2 — Deterministic fixtures for T01–T12 | **Partial** | Synthetic fixtures exist; the specific integration cases are not covered end-to-end. |
| P2 — Runtime network/model downloads | **Pass** | No runtime network access or model download in the pipeline. |

**Definition of done:** none of the 11 criteria in the handoff is fully satisfied. Several are partially satisfied by isolated modules.

---

## 2. Critical findings

### F1 — P0 — The pipeline bypasses ingestion, schema mapping and full validation

**Evidence**

- `src/pipeline.py:80-93` reads files directly:
  - `pd.read_csv(root)` for a single file
  - `pd.read_csv(scenario_dir / "operating_data.csv")`
  - optional `weather.csv`, `devices.csv`, `forecast.csv`, `event_log.csv`
- `src/pipeline.py:98-99` uses only:
  - `map_columns(operating.columns, ...)` — a header-only compatibility helper
  - `validate_frame(operating)` — the lightweight DataFrame validator
- A repository search shows `ingest_file()`, `map_table()` and `validate_table()` are **never called by the pipeline**.
- `src/ingestion.py` supports CSV and every Excel sheet; `src/schema_mapping.py` supports unit extraction/conversion; `src/validation.py` supports gaps, duplicates per device, flatlines, cumulative resets, night generation, etc. None of this reaches the integration boundary.

**Observed impact**

| Case | Observed result |
|---|---|
| Directory containing only `operating_data.xlsx` | `ValueError: No operating data found in input directory` |
| Aliased headers (`Reading time`, `AC Output (kW)`, `asset`) | `ValueError: interval.timestamp_utc: np.float64(nan) is not of type 'string', 'null'` |
| CSV with preamble / non-canonical names | Ingestion would handle it; pipeline does not use ingestion |
| Gaps / duplicates / flatlines | Not reported in the output |

**Required fix direction**

Create one real service boundary, e.g. `analyze(inputs, config) -> ContractOutput`, that:

1. calls `ingest_file()` for CSV/XLSX (including sheet selection),
2. calls `map_table()` and carries the mapping manifest forward,
3. calls `validate_table()` and surfaces its checks in `limitations`/`data_quality`,
4. passes the mapped, converted frame to baseline/anomaly/attribution.

`run_pipeline()` and the CLI should become thin wrappers around that function.

---

### F2 — P0 — Energy values are fabricated or silently defaulted

**Evidence**

- `src/pipeline.py:100` builds the baseline from `operating` only. It does **not** merge `devices.csv` (capacity) or `weather.csv` (irradiance), even though `detect_anomalies()` does merge them internally (`src/anomaly.py:96-137`).
- In the shipped synthetic scenario, capacity is in `devices.csv` and POA is in `operating_data.csv`. The baseline therefore has no AC capacity → `expected_power_kw` is all `NaN`.
- `src/pipeline.py:123` does:
  ```python
  expected_energy = float(pd.to_numeric(base_report.get("expected_energy_kwh", ...)).sum())
  ```
  Pandas sums an all-`NaN` series to **`0.0`**, not `None`.
- `src/pipeline.py:116-120`:
  ```python
  forecast_energy = ... forecast.csv ...
  if forecast_energy is None:
      forecast_energy = ... baseline expected_energy ...
  ```
  This relabels the baseline as a forecast, directly violating the handoff’s P1/T10 rule.
- `src/pipeline.py:124-125`:
  ```python
  if expected_energy is None and actual_energy is not None:
      expected_energy = actual_energy
  ```
  This can relabel actual energy as expected energy.

**Observed result on the shipped scenario**

```text
analysis_status: ok
waterfall.status: ok
forecast_energy: 5282.331267
actual_energy:   5374.120967
expected_energy: 0.0
weather_effect:  -5282.331267
plant_effect:     5374.120967
reconciled:       true
limitation:       "AC capacity is unavailable; expected power is unavailable."
```

The waterfall reconciles only because `E = 0` was invented. This is the highest-priority correctness defect.

**Required fix direction**

1. Merge device/weather context **before** the baseline (same join keys as the anomaly stage).
2. Convert an all-`NaN` series to `None`, never `0.0`.
3. Remove both fallbacks: forecast must remain `null` without a supplied/valid forecast; expected must remain `null` without a valid baseline.
4. Add an explicit `energy_basis` / `completeness` object so the consumer knows which values are measured, derived or unavailable.
5. Fail the waterfall as `unavailable` when `E` is unavailable, regardless of `F` and `A`.

---

### F3 — P0/P1 — Interval energy silently assumes 60 minutes

**Evidence:** `src/pipeline.py:30-38`

```python
if "ac_power_kw" in frame.columns:
    interval_hours = (interval_minutes or 60.0) / 60.0
```

`run_pipeline()` never passes `interval_minutes`, so every power-only dataset is treated as hourly.

**Observed impact:** a 15-minute synthetic scenario with `energy_kwh` removed returned:

- pipeline `actual_energy = 9361.17 kWh`
- true energy (`Σ power × 0.25 h`) = `2340.29 kWh`
- **4× overstatement**, with no limitation or warning.

This directly violates P1 *“use actual interval duration; do not silently assume 60 minutes.”*

**Required fix direction:** derive duration from resolved timestamps per device; if it cannot be established, return `null` plus a limitation. Never use a silent default.

---

### F4 — P0 — The output contract is present but not strong enough to integrate against

**Evidence**

- `src/pipeline.py:158-162` sets `interval` to only the first assessment row:
  ```json
  {"timestamp_utc": "...", "device_id": "INV-01", "source_rows": 144}
  ```
  It does not include the analysed time range, timezone, interval duration or device coverage. For multi-device data, `device_id` is just the first device.
- `forecast_energy`, `actual_energy` and `deviation` are bare numbers: no unit, aggregation period or sign convention in the payload.
- `configs/output_schema.json`:
  - `analysis_status` is any string.
  - `anomalies` and `hypotheses` are untyped arrays.
  - `additionalProperties: true`.
  - There is no enum for status, no unit fields and no error object.
- The contract is effectively defined three times: the dataclass in `src/contract.py:17-49`, the manual payload mutations in `src/pipeline.py:175-197`, and the JSON Schema. The pipeline writes the same fields twice.
- `status`, `message` and `metrics` are included in the canonical schema even though the handoff explicitly asks whether these convenience fields belong there and warns against two competing schemas.
- `model_version = "1.0.0"` is emitted even though no trained model exists and the physics baseline is the active method. That can be read as a production model version.

**Observed schema weakness:** this payload was accepted by `validate_contract()`:

```json
{
  "schema_version": "9.9.9",
  "analysis_status": "banana",
  "anomalies": [1, 2, 3],
  "hypotheses": [{"anything": true}],
  "waterfall": {"status": "whatever", "reconciled": true}
}
```

**Required fix direction**

- Define enums:
  - `analysis_status`: `success | partial | invalid_input | failed`
  - per-capability status: `available | unavailable | not_applicable | failed`
- Add units, timezone, interval duration, analysed range and aggregation period.
- Add `method`/`model_status` (`physics_baseline`, `residual_model_not_available`, etc.).
- Add a structured `errors[]` and `data_quality` block.
- Make nested `anomalies` and `hypotheses` schemas strict.
- Use one builder and validate every result, including error results.
- Remove or explicitly document `status/message/metrics` as non-canonical convenience fields.

---

### F5 — P0 — Status semantics are ambiguous and can mask unavailability

**Evidence:** `src/pipeline.py:145-147`

```python
analysis_status = "ok" if waterfall_result.get("status") in {"ok", "warning"} else "unavailable"
if anomalies.get("status") == "warning":
    analysis_status = "warning"
```

- The status vocabulary is `ok/warning/unavailable`, not the handoff’s `success/partial/invalid_input/failed`.
- An anomaly warning **overrides** an unavailable waterfall. A result can therefore say `warning` when the core energy analysis is unavailable.
- There is no `invalid_input` status and no `failed` status.
- The shipped scenario says `ok` while a core input is unavailable.

**Required fix direction:** define and enforce one status enum and a precedence table. Unavailability of a required component must produce `partial` or `invalid_input`, never `success`.

---

### F6 — P0 — No quick-snapshot mode or capability gating

**Evidence**

- There is no snapshot flag, input mode or capability matrix in `run_pipeline()`.
- A one-row snapshot returns:
  ```text
  analysis_status: ok
  waterfall.status: ok
  actual_energy: 0.0
  anomalies: 0
  ```
- No limitation says that persistence, peer comparison, trend/CUSUM and event correlation are unavailable for a single snapshot.
- `anomaly.persistence_n = 2` (`configs/defaults.yaml:101`) and peer minimum 3 devices (`:95`) exist, but there is no snapshot-specific gate.

**Required fix direction:** add `analysis_mode: "snapshot" | "full"`, and a `capabilities` block with explicit `available/unavailable/not_applicable` per check. Snapshot mode must suppress time-series claims by construction.

---

### F7 — P0 — Error handling exposes raw exceptions

**Observed cases**

| Input | Result |
|---|---|
| Empty `operating_data.csv` | `pandas.errors.EmptyDataError: No columns to parse from file` |
| Nonexistent path | `FileNotFoundError: Input data path does not exist: ...` |
| Aliased headers | `ValueError: interval.timestamp_utc: np.float64(nan) is not of type 'string', 'null'` |
| Excel-only directory | `ValueError: No operating data found ...` |

The CLI prints the exception; there is no `error_code`, no safe user message and no schema-valid error response.

**Required fix direction:** wrap all input and analysis failures in a structured result, e.g.:

```json
{
  "schema_version": "2.0.0",
  "analysis_status": "invalid_input",
  "errors": [{"code": "EMPTY_FILE", "message": "The operating-data file is empty.", "field": null}]
}
```

Never return raw stack traces or local paths to the frontend.

---

### F8 — P0/P1 — Mapping results and unit conversions are not consumed downstream

**Evidence**

- `map_columns()` (`src/schema_mapping.py:865-874`) returns `{column: role}` only. It discards detected units, conversion factors, confidence, unresolved reasons and the mapping manifest.
- `baseline._mapping_lookup()` (`src/baseline.py:76-94`) and `anomaly._mapping_lookup()` (`src/anomaly.py:35-47`) expect an object with `.fields` or a dict with `"fields"`. Passing the `map_columns()` dict makes them return `{}`.
- Consequently, mapping has no effect on baseline or anomaly column selection; both fall back to hardcoded candidate names.
- `unresolved_fields` (`src/pipeline.py:111-114`) lists source columns with no role. It does **not** list required canonical fields that are missing.
- In the missing-power test, `unresolved_fields` was `['scenario_id', 'synthetic']`; `power_ac` was not listed.

**Required fix direction:** pass the full `MappingResult` (or its manifest) into every stage, apply conversions once at the boundary, and report both unresolved source fields and missing required canonical fields.

---

### F9 — P1 — Validation results are discarded before the contract

**Evidence**

- `src/pipeline.py:99` calls `validate_frame()`, which only checks:
  - duplicate raw strings in a column literally named `timestamp`,
  - out-of-order values in that column,
  - missing values,
  - a column literally named `power`.
- The synthetic data uses `timestamp_utc`, so duplicates/order are not checked at all.
- The full `validate_table()` report (gaps, per-device duplicates, flatlines, cumulative resets, night generation, plausibility) is never called.
- The output only receives `metrics.valid` (`src/pipeline.py:195`); the checks, affected devices, time ranges and limitations are dropped.

**Observed impact:** T05 (missing intervals) and T06 (duplicates/out-of-order) cannot be evidenced from the integration output, even though the underlying module can produce the evidence.

**Required fix direction:** call `validate_table()` and expose a compact `data_quality` summary plus limitations. Do not collapse a rich report into a boolean.

---

### F10 — P1 — Forecast and actual aggregation ignore alignment and completeness

**Evidence**

- `src/pipeline.py:117-118` sums `forecast_energy_kwh` without checking that forecast timestamps cover the operating period or share the same interval.
- `src/pipeline.py:122` sums `energy_kwh` across all devices/rows without checking duplicates, gaps or completeness.
- Pandas `sum()` skips `NaN`, so partial data silently understates totals without a completeness flag.

**Required fix direction:** align forecast and actual on a common interval; reject upsampling; report coverage, missing intervals and duplicate handling; never sum across unmatched periods.

---

### F11 — P1 — Attribution confidence is hardcoded and output volume is uncontrolled

**Evidence**

- `src/attribution.py:177-178`:
  ```python
  return {CONFIRMED_EVENT: 0.85, SUSPECTED: 0.60, UNRESOLVED: 0.15}.get(status, 0.15)
  ```
  No calculation, calibration or meaning is defined.
- `src/pipeline.py:42-64` runs `explain_interval()` for **every** assessment row, including rows with no alert.
- The shipped one-day, three-inverter scenario produced **144 hypotheses** and **144 evidence strings**, almost all `unresolved` (“no specific rule produced enough evidence”).
- A month of 15-minute multi-inverter data would produce tens of thousands of hypotheses, bloating the payload and inviting the LLM to over-explain noise.

**Required fix direction:** emit hypotheses only for supported findings (or aggregate by event window/device), cap/group the list, and define confidence as a documented function of evidence strength, persistence and data quality.

---

### F12 — P1/P2 — Reproducibility, documentation and handover gaps

**Evidence**

- `model_version`, `mapping_version` and `schema_version` are hardcoded in `src/pipeline.py:172-189` and `src/contract.py:12-14`.
- No config hash, vocab version, seed or model artifact identifier appears in the output.
- `README.md:8` hardcodes `D:\Storage\Downloads\globathon_models`, so a fresh clone cannot follow the quick start.
- README does not state the supported Python version, the `pytest` command, or the exact canonical input/output schema.
- `requirements.txt` uses open-ended lower bounds (`numpy>=1.26`, etc.); `lightgbm`, `scikit-learn` and `pvlib` are declared but not imported anywhere.
- `reports/expected_benchmark.md` says LightGBM was not installed, while `requirements.txt` requires `lightgbm>=4.0`.
- README section 10 describes a `src/` package with subdirectories (`ingestion/`, `schema_mapping/`, etc.); the actual code is flat modules (`src/ingestion.py`, etc.).
- There is no committed sample output JSON and no sample Excel file, both explicitly requested in the handover checklist.
- No runtime or memory measurement exists.

**Required fix direction:** publish one canonical schema document, add sample CSV/XLSX/JSON, pin dependencies, document Python version and commands, add config/vocab/model identifiers to the output, and record measured runtime.

---

## 3. Test-case matrix against handoff Section 6

| ID | Required behaviour | Observed result | Status |
|---|---|---|---|
| **T01** Valid dataset | Schema-valid output and metrics | Runs and validates, but `expected_energy = 0.0` while a limitation says expected power is unavailable | **Partial** |
| **T02** Excel upload | Same logical result as CSV | `ValueError: No operating data found` for an `.xlsx`-only directory | **Fail** |
| **T03** Header aliases | Deterministic mapping or explicit unresolved mapping | Alias file crashes contract validation on `NaN` timestamp; mapping not applied downstream | **Fail** |
| **T04** Missing required column | Partial/invalid status, unresolved field listed, no fabrication | Status `unavailable`, but forecast is still populated, `power_ac` is not listed as unresolved, no error code | **Partial/Fail** |
| **T05** Missing intervals | Gaps disclosed, no interpolation | Full gap checker exists but is not called; no gaps appear in output | **Fail** |
| **T06** Duplicate/out-of-order rows | Deterministic handling and disclosure | Lightweight checker only looks for a literal `timestamp` column; synthetic uses `timestamp_utc`; no disclosure | **Fail** |
| **T07** Unit mismatch | Reject or normalize with explicit tested conversion | Conversion logic exists in `schema_mapping.py` but is not used by the pipeline | **Fail** |
| **T08** Single snapshot | No persistence/trend claims; history checks unavailable | Returns `ok`, waterfall `ok`, `actual_energy = 0.0`, no snapshot limitation | **Fail** |
| **T09** Conflicting signals | Conflict surfaced; no definitive cause | No cross-source conflict detection; event log is only checked for time overlap | **Fail** |
| **T10** No forecast | `forecast_energy` unavailable; baseline not relabelled | `forecast_energy = 0.0` when `forecast.csv` is absent | **Fail** |
| **T11** Waterfall reconciliation | Reconcile within tolerance; no double counting | Arithmetic unit tests pass, but E2E reconciles only because `E` is fabricated as `0.0` | **Fail in E2E** |
| **T12** Empty/corrupt file | Controlled error response | Raw `EmptyDataError` | **Fail** |

**Existing test suite:** `python -m pytest -q` → **57 passed in 28.07s**. The suite is green, but `tests/test_end_to_end.py` only asserts that the pipeline runs and returns a schema version. It does not assert the semantics above.

---

## 4. Quick analysis vs full analysis capability

| Capability | Handoff expectation | Current reality |
|---|---|---|
| Basic type/range validation | Supported in both modes | Available in `validation.py`; not wired to the contract |
| Baseline comparison | Snapshot only with required context; full where inputs permit | Implemented; E2E baseline lacks device/weather merge |
| Persistence detection | Unavailable for snapshot; full if enough history | Implemented (`persistence_n = 2`); no snapshot gate |
| Peer comparison | Only with peer data | Implemented (minimum 3 comparable devices); no snapshot gate |
| Trend/drift analysis | Unavailable for snapshot; full if enough history | CUSUM implemented; no explicit history contract |
| Event correlation | Only with event context; full if timestamps align | Partial: overlap matching only; event timestamps not normalized |
| Energy waterfall | Only with comparable energy/reference values | Arithmetic implemented; E2E reference is invalid |
| Quick snapshot mode | Required second input mode | **Not implemented** |

---

## 5. Answers to the handoff’s Section 10 questions

1. **Exact public entry point?**
   - Python: `src.pipeline.run_pipeline(data_path, output_path=None, *, config=None)`
   - CLI: `python ML-models/scripts/run_pipeline.py --inputs <dir> --output <json>`
   - No HTTP service. Path-based only; no in-memory DataFrame/records API.

2. **Does `run_pipeline()` use `ingestion.py` for CSV and Excel?**
   - **No.** It uses `pandas.read_csv` directly and only looks for fixed filenames. Excel is not accepted.

3. **Exact columns, units, interval and timezone required?**
   - **No published canonical schema.** De facto required names are inferred from candidate lists in `baseline.py`/`anomaly.py` (e.g. `timestamp_utc`, `ac_power_kw`, `poa_irradiance_w_m2`, `rated_ac_power_kw`).
   - Units are inferred from header text only where the baseline helper recognizes them; the mapping conversion layer is not used.
   - Interval is discovered by ingestion but not used by the pipeline; it defaults to 60 minutes.
   - Timezone is not normalized to UTC in the pipeline; raw timestamp strings flow into the output.

4. **Which anomaly detectors and attribution methods are implemented, and which are placeholders?**
   - Implemented: peer median/MAD with persistence, residual shortfall with persistence, CUSUM, night/low-irradiance/low-expected suppression, rule-based attribution with event-log overlap.
   - Placeholder: LightGBM residual model (`baseline.residual_model()` returns `not_available`).
   - Not present as source: Isolation Forest (only stale `.pyc` files remain; no `.py` implementation or test).
   - `model_adapter.py` is explicitly a stub, correctly labelled.

5. **Is LightGBM trained and integrated, or is physics the active fallback?**
   - Physics baseline is the active method. LightGBM is not fitted or integrated; `reports/expected_benchmark.md` confirms it was not installed.

6. **What does each `analysis_status` mean, and which fields can be null?**
   - Current values: `ok`, `warning`, `unavailable` only.
   - No documented enum, precedence or meaning. `ok` can coexist with an unavailable baseline.
   - Most numeric fields are nullable in the schema, but nullability is not documented per field.

7. **How are `actual_energy`, `forecast_energy`, expected/baseline energy and deviation defined?**
   - `actual_energy`: sum of `energy_kwh`, or sum of `ac_power_kw × assumed 1 hour` if energy is absent.
   - `forecast_energy`: sum of `forecast_energy_kwh`, falling back to baseline expected energy.
   - Expected energy: sum of physics-baseline `expected_energy_kwh`, falling back to actual energy.
   - `deviation`: `actual − forecast`.
   - The fallbacks make these definitions unsafe for integration.

8. **Minimum history for persistence, peer comparison and trend analysis?**
   - Peer comparison: at least 3 comparable devices at the same timestamp (`anomaly.peer_min_devices`).
   - Persistence: 2 consecutive assessable intervals (`anomaly.persistence_n`).
   - CUSUM: slack 0.05, threshold 0.50; no minimum-history statement.
   - No documented minimum for trend/drift or snapshot unavailability.

9. **In-memory DataFrames/records, or file paths? Preferred integration method?**
   - File paths only. No in-memory API. The preferred boundary is not documented.

10. **Can the ML member provide sample input, sample output and passing tests before integration?**
    - Sample synthetic CSV scenarios exist.
    - **No sample Excel file and no committed sample output JSON.**
    - Tests pass (`57 passed`), but they do not cover T01–T12 semantics.

---

## 6. Recommended remediation plan

### Phase 0 — P0 blockers (must land before backend integration)

1. **Create the real service boundary**
   - New `analyze(inputs, config)` accepting either paths or in-memory frames.
   - Wire `ingest_file` → `map_table` → `validate_table` → baseline → anomaly → attribution → waterfall.
   - Support CSV and XLSX, sheet selection, explicit timezone and interval overrides.
   - Keep `run_pipeline()`/CLI as thin adapters.

2. **Fix energy semantics**
   - Merge device and weather context before the baseline.
   - Convert all-`NaN` series to `None`, never `0.0`.
   - Remove the forecast→baseline and expected→actual fallbacks.
   - Derive interval duration from timestamps; never default to 60 minutes.
   - Align forecast and actual periods; report coverage and completeness.

3. **Publish contract v2**
   - Status enums and capability statuses.
   - Units, timezone, interval range/duration, aggregation period.
   - `errors[]`, `data_quality`, `energy_basis`, `method`/`model_status`.
   - Strict nested schemas for anomalies/hypotheses.
   - One builder; validate every success, partial, invalid-input and failed result.
   - Add `config_hash`, `vocab_version`, seed and real model identifier.

4. **Add snapshot mode and capability gating**
   - `analysis_mode: snapshot | full`.
   - Mark persistence, peer, trend, CUSUM and event correlation `unavailable`/`not_applicable` for snapshots.

5. **Structured error handling**
   - No raw exceptions or local paths at the boundary.
   - Error codes for empty file, unreadable file, missing required column, unresolved timestamp, unsupported format, etc.

### Phase 1 — Analytical correctness (P1)

6. Surface `validate_table()` checks and limitations in the contract.
7. Report missing required canonical fields and unresolved source fields separately.
8. Add cross-source conflict detection (weather vs device vs event log).
9. Define minimum history per detector and expose it.
10. Replace hardcoded confidence with a documented evidence-based score.
11. Emit hypotheses only for supported findings; aggregate/cap output volume.
12. Tie waterfall losses to eligible intervals and one primary cause; separate weather, plant and unresolved contributions.

### Phase 2 — Handover and operational readiness (P2)

13. Publish canonical input/output schema docs, enums, units, nullability and sign conventions.
14. Add sample CSV, sample XLSX, and one schema-valid sample JSON output.
15. Add T01–T12 end-to-end tests, including negative/error cases and contract tests.
16. Pin dependencies and remove unused ones; state the supported Python version.
17. Fix README hardcoded paths; document install, run and pytest commands; align the documented repository structure with the actual code.
18. Measure and record runtime/memory on representative and maximum datasets.
19. Add upload validation policy (extension, size, encoding, sheet selection) and temporary-file cleanup guidance for the backend.

---

## 7. What should be preserved

These parts are strong and should not be rewritten during integration:

- `src/ingestion.py` — adaptive CSV/XLSX structure, header, timestamp and layout discovery.
- `src/schema_mapping.py` — deterministic vocabulary scoring, unit extraction, ambiguity handling and mapping manifest.
- `src/validation.py` — per-device duplicate/order/gap checks, flatlines, cumulative resets, plausibility and night generation.
- `src/baseline.py` — explicit physics model, unit conversion, actual-duration energy calculation and honest warnings.
- `src/anomaly.py` — peer/MAD, persistence, CUSUM and suppression logic with missing data kept unavailable.
- `src/attribution.py` — separation of observed facts, hypotheses, confirmed events and unresolved causes.
- `src/counterfactual.py` — signed waterfall arithmetic, unit-aware conversion and single-primary-cause ledger.
- `src/model_adapter.py` — correctly labelled stub, not presented as a production model.
- `tests/` — good unit coverage of the individual modules; the gap is end-to-end contract coverage, not module logic.

The central message: **the analytical building blocks are largely there; the integration layer is currently bypassing them and inventing values.** Fixing the boundary and the energy semantics is the shortest path to alignment.

---

## Appendix A — Commands and observed results

```text
cd ML-models
python -m pytest -q
57 passed in 28.07s
```

Key reproduction cases:

| Case | Observed |
|---|---|
| `run_pipeline("artifacts/synthetic_smoke/scenario_000")` | `analysis_status=ok`, `expected_energy_kwh=0.0`, `weather_effect_kwh=-5282.33`, `reconciled=true` |
| Remove `forecast.csv` | `forecast_energy=0.0` (expected `null`) |
| Excel-only directory | `ValueError: No operating data found` |
| Alias headers | `ValueError: interval.timestamp_utc: np.float64(nan) is not of type 'string', 'null'` |
| One-row snapshot | `analysis_status=ok`, `waterfall.status=ok`, `actual_energy=0.0`, no snapshot limitation |
| Empty CSV | `pandas.errors.EmptyDataError` |
| Missing path | `FileNotFoundError` |
| 15-minute data without `energy_kwh` | `actual_energy=9361.17` vs true `2340.29` (4×) |
| Invalid contract payload | `analysis_status="banana"`, `schema_version="9.9.9"`, `anomalies=[1,2,3]` accepted |

**Alignment conclusion:** proceed with integration only after Phase 0. The backend/LLM boundary should not consume the current output as authoritative ML evidence.
