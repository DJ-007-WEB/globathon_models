# Integration Remediation Implementation Report

## Status

All five remediation items from `ML-models/Integration.docx` are implemented and covered by the automated suite.

- Schema contract version: `2.0.0`
- Public service boundary: `src.service.analyze(...)`
- Existing compatibility wrapper: `src.pipeline.run_pipeline(...)`
- Test result: `73 passed`
- Synthetic scenario and CLI output both pass strict JSON-Schema validation.

## 1. Real `analyze()` service boundary

Added `src/service.py` with `analyze()` as the single supported end-to-end boundary.

`analyze()` now orchestrates:

1. Input loading from a scenario directory, one CSV/XLSX file, a `DataFrame`, or a named mapping.
2. Ingestion and timestamp detection.
3. Schema mapping and canonical-column construction.
4. Data-quality validation.
5. Device and weather context merging.
6. Physics baseline expected energy/power.
7. Anomaly detection.
8. Attribution for alert intervals only.
9. Energy waterfall reconciliation.
10. Contract-v2 validation and optional JSON output.

`src/pipeline.py` is now a thin compatibility and CLI wrapper around `analyze()`. It preserves `run_pipeline()` and adds CLI options for mode, time zone, interval, plant id and worksheet selection.

Supported inputs include:

- `operating_data`, `weather_data`, `device_data`, `forecast_data`, `event_log`, `metadata`
- Files named by role in a scenario directory
- A single operating-data file
- In-memory pandas objects

## 2. Energy semantics

- Device context is merged before the baseline and anomaly stages.
- Weather context is merged before the baseline and anomaly stages.
- Forecast context is kept independent and is never merged into operating data.
- Forecast, expected and actual energy are calculated independently.
- No component falls back to another component.
- Missing values remain `null`/`NaN`; they are never converted to `0.0`.
- Actual energy from power uses timestamp-derived interval durations.
- Expected baseline energy also uses timestamp-derived interval durations.
- The service does not use metadata `sampling_interval_minutes` to override actual timestamps.
- When interval duration cannot be established, energy derived from power is unavailable rather than assumed to be hourly.
- Partial totals expose `completeness` and `status: partial`.
- The waterfall keeps `potentially_recoverable_energy_kwh` as `null` because recoverability needs operational/commercial evidence.

## 3. Strict contract v2

`configs/output_schema.json` now uses Draft 2020-12 with:

- `schema_version = "2.0.0"`
- Closed status enums:
  - `success`, `partial`, `invalid_input`, `failed`
  - `snapshot`, `full`
  - `available`, `partial`, `unavailable`, `not_applicable`
  - `ok`, `warning`, `unavailable`
- `additionalProperties: false` at the top level and nested item schemas.
- Explicit units:
  - power `kW`
  - energy `kWh`
  - irradiance `W/m2`
  - temperature `C`
  - duration `minutes`
- Explicit time-zone and timestamp-basis fields.
- Interval start/end, duration, sampling interval, device count and row count.
- Structured `energy` components with value, status, source, completeness, aggregation period, unit and reason.
- `data_quality` with checks, counts and limitations.
- `capabilities` for validation, baseline, persistence, peer comparison, trend analysis, event correlation and waterfall.
- `method` and `model_status`.
- Structured `errors`.
- Separate `unresolved_fields` and `missing_required_fields`.

`src/contract.py` now builds, validates and writes this v2 payload. A small legacy `build_contract(status, message, metrics)` compatibility path maps old statuses into v2 statuses.

## 4. Snapshot mode and structured errors

Snapshot mode is selected automatically when the operating data has one timestamp, or explicitly with `mode="snapshot"`.

In snapshot mode:

- Persistence, peer comparison and trend capabilities are `not_applicable`.
- No anomaly alerts or attribution hypotheses are emitted.
- Energy components remain available only when their own inputs are available.
- The result is marked `partial` because time-series evidence is not claimed.

Structured errors include:

- `INPUT_NOT_FOUND`
- `UNSUPPORTED_FILE_TYPE`
- `EMPTY_FILE`
- `UNREADABLE_FILE`
- `MISSING_OPERATING_DATA`
- `AMBIGUOUS_INPUT_FILES`
- `SHEET_NOT_FOUND`
- `MISSING_REQUIRED_FIELDS`
- `AMBIGUOUS_TIMESTAMP`
- `INVALID_ARGUMENT`
- `INTERNAL_ERROR`

Ambiguous operating timestamps are returned as a non-fatal `AMBIGUOUS_TIMESTAMP` error with a `partial` result, so a usable energy total is not discarded.

## 5. T01–T12 end-to-end tests

Added `tests/test_integration_contract.py` with coverage for:

| Test | Coverage |
|---|---|
| T01 | Full synthetic scenario through `analyze()` with actual, expected, forecast and reconciled waterfall |
| T02 | Power-only 15-minute data uses 900-second durations, not a 60-minute default |
| T03 | Alias mapping and canonical columns |
| T04 | Missing measurements remain `null`, not zero |
| T05 | Time gaps are reported and make the result partial |
| T06 | Duplicate and out-of-order timestamps are reported |
| T07 | Explicit unit conversion (`W`, `Wh`, `kW/m2`) |
| T08 | Snapshot mode does not claim time-series evidence |
| T09 | Logged outage is not confirmed when output is not low |
| T10 | Missing forecast stays null and makes the result partial |
| T11 | Missing actual measurements are explicit |
| T12 | Structured input errors and ambiguous-timestamp errors |

Additional fixes made while implementing the tests:

- Added canonical aliases for `ac_power_kw`, `energy_kwh`, `poa_irradiance_w_m2`, `rated_ac_power_kw`, `rated_dc_power_kw`, forecast roles and related fields.
- Added negative-token disambiguation so capacity, power, cumulative energy, interval energy, temperature coefficient and forecast roles do not compete.
- Added `dc_capacity`, `inverter_efficiency`, `system_losses`, `temperature_coefficient`, `sun_elevation`, `latitude`, `longitude`, `forecast_energy`, `forecast_power` and `forecast_poa` roles.
- Added device/weather context merge and canonical `rated_ac_power_kw`/`rated_dc_power_kw`.
- Added actual interval-duration derivation for energy calculations.
- Improved validation gap detection so a single large gap does not inflate the median interval and hide itself.
- Filtered timestamp-ambiguity warnings from device and event-log files where a resolved timestamp is not required.
- Allowed empty optional files to be ignored with a limitation instead of failing the whole analysis.

## Verification

```powershell
python -m pytest -q
# 73 passed
```

CLI verification:

```powershell
python -m src.pipeline --inputs <scenario_directory> --output <result.json> --mode auto
```

The emitted JSON is validated against `configs/output_schema.json` before it is written.

## Files changed

- `src/service.py` (new)
- `src/contract.py`
- `src/pipeline.py`
- `src/schema_mapping.py`
- `src/validation.py`
- `src/__init__.py`
- `configs/output_schema.json`
- `configs/schema_vocab.yaml`
- `configs/defaults.yaml`
- `tests/test_integration_contract.py` (new)
- `tests/test_contract.py`
- `tests/test_end_to_end.py`
- `tests/test_schema_mapping.py`

## Residual limitations

- The active expected-energy method is the deterministic physics baseline. LightGBM remains unavailable; `model_status` is `physics_baseline_active`.
- Missing DC capacity falls back to a configured DC/AC ratio and is disclosed in limitations.
- Missing module temperature uses the documented baseline assumption and is disclosed.
- Forecast coverage is matched on exact timestamps; a different forecast cadence is marked partial rather than silently resampled.
- Partial energy totals are sums over valid readings, with `completeness` exposing the coverage.
- Event-log entries alone are not treated as confirmed causes; interval evidence is required.
- Recoverable energy is not estimated without operational or commercial evidence.
- Unresolved local time zones remain explicit; UTC is not invented.
