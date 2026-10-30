# Stage 1: Ingestion, Schema Mapping and Validation

Status: implementation complete for review. This stage covers ingestion, deterministic schema mapping and data-quality validation only. No forecasting, baseline, anomaly, attribution or recovery work was started.

## Implemented functionality

- Adaptive CSV and XLSX ingestion via `src/ingestion.py`.
  - Inspects every Excel sheet and detects the header row.
  - Handles variable-width CSV preambles with `csv.reader`.
  - Detects wide (device in column names) and long (device-column) layouts.
  - Extracts device labels without assuming inverter count.
  - Detects full timestamps and separate date/time columns.
  - Resolves day/month order only from explicit evidence.
  - Resolves time zones only from explicit values, header text, caller input or config.
  - Normalizes resolved timestamps to timezone-aware UTC and records the original format/time zone.
  - Detects the sampling interval.
  - Keeps missing readings as `NaN`/`null`; never fills them with zero.
  - Preserves fully empty source columns by default and reports them as all-missing.
- Deterministic schema mapping via `src/schema_mapping.py`.
  - Header/alias scoring plus value-based validation.
  - Unit extraction from header text; bare magnitudes are not used to infer units.
  - Disambiguates POA vs GHI and AC vs DC where the evidence supports it.
  - Handles power, interval energy and cumulative energy roles.
  - Supports explicit unit conversions.
  - Leaves ambiguous or unsupported mappings unresolved and records the reason.
  - Produces a JSON-safe mapping manifest with source column, role, unit, conversion, confidence and provenance.
- Validation via `src/validation.py`.
  - Duplicate timestamps, out-of-order timestamps and time gaps are checked **per device** in long layout.
  - Missing-value and all-missing-column reporting.
  - Impossible-value checks, optional capacity checks and optional night-time generation checks.
  - Cumulative-energy reset detection and repeated-value/flatline detection.
  - Structured report with status, counts, affected devices, example time ranges and limitations.
  - Time-zone, mapping and header ambiguity are reported rather than silently resolved.
- Shared configuration helpers in `src/config.py` and JSON-safe serialization.
- Reproducible synthetic demo in `scripts/stage1_demo.py`.

## Configuration

- `configs/defaults.yaml`: validation thresholds, plausibility ranges, empty-column behavior and mapping thresholds.
- `configs/schema_vocab.yaml`: role aliases, unit aliases, device-label vocabulary and stopwords.
- `data/README.md`: dataset registry and observed field notes; licences that were not verified are marked as such.
- No data, credentials, virtual environments or generated artifacts are committed.

## Test results

Command run from `ML-models/`:

```text
python -m pytest -q
```

Actual result from the latest completed run:

```text
.....................................                                    [100%]
37 passed in 12.69s
```

The tests cover, among other cases:

- CSV, XLSX, multiple sheets, preamble headers and variable-width rows.
- Wide and long layouts, device extraction and false device-column detection.
- Timestamp formats, ambiguous day/month order, separate date/time and time-zone ambiguity.
- Missing values remaining missing, not zero, and fully empty columns being preserved.
- AC/DC and POA/GHI disambiguation, unit conversion and unresolved generic headers.
- Per-device duplicate/order/gap checks in long layout.
- Capacity checks, cumulative resets, flatlines, night generation and ambiguity reporting.

## Synthetic demo

Command run from `ML-models/`:

```text
python scripts\stage1_demo.py
```

The fixture is explicitly synthetic. It has 9 rows, 2 devices, a 15-minute interval and UTC timestamps ending in `Z`. It writes the fixture and full manifest only under the git-ignored `artifacts/stage1_demo/` directory.

Actual demo summary:

- Layout: `wide`
- Devices: `inv-01`, `inv-02`
- Timestamp: resolved UTC, format `YYYY-MM-DD HH:MM:SS`, sampling interval `900` seconds
- Source columns: 8; derived columns: 4
- Mapped roles: `timestamp`, `power_ac`, `irradiance_poa`, `module_temperature`, `irradiance_ghi`
- Unresolved fields: none
- Validation status: `warning`
- Validation counts: `12` checks, `0` fail, `8` warning, `3` pass, `1` not checked

Demo checks:

| Check | Status | Count | Devices |
|---|---|---:|---|
| Duplicate timestamps | pass | 0 | - |
| Out-of-order timestamps | pass | 0 | - |
| Time gaps | pass | 0 | - |
| Missing values | warning | 1 | `inv-02` |
| Suspicious flatline | warning | 7 | `inv-01`, `inv-02`, site GHI |
| Night-time generation | not checked | 0 | - |

The warnings are expected artifacts of the fixture: one AC-power cell is deliberately blank, and the short fixture repeats constant values. They are evidence to review, not confirmed faults.

Manifest excerpt from `artifacts/stage1_demo/manifest.json`:

```json
{
  "fixture_kind": "synthetic",
  "ingestion": {
    "ok": true,
    "tables": [
      {
        "row_count": 9,
        "column_count": 8,
        "layout": {
          "layout_type": "wide",
          "device_id_source": "column_names",
          "devices": ["inv-01", "inv-02"]
        },
        "timestamp": {
          "status": "resolved",
          "format": "YYYY-MM-DD HH:MM:SS",
          "timezone": "UTC",
          "sampling_interval_seconds": 900.0
        }
      }
    ]
  },
  "mapping": {
    "role_to_columns": {
      "timestamp": ["timestamp"],
      "power_ac": ["INV-01 AC Power (kW)", "INV-02 AC Power (kW)"],
      "irradiance_poa": ["INV-01 POA Irradiance (W/m2)", "INV-02 POA Irradiance (W/m2)"],
      "module_temperature": ["INV-01 Module Temp (C)", "INV-02 Module Temp (C)"],
      "irradiance_ghi": ["Site GHI (W/m2)"]
    },
    "unresolved_fields": []
  },
  "validation": {
    "status": "warning",
    "counts": {
      "checks": 12,
      "fail": 0,
      "warning": 8,
      "pass": 3,
      "not_checked": 1
    }
  }
}
```

## Real-dataset smoke checks

These are compatibility checks, not accuracy or performance evaluations. All listed files ingested successfully. Validation produced no `fail` statuses after long-layout timestamp checks were corrected to run per device. Source-column counts exclude the four derived timestamp/order columns added internally.

| File | Source cols | Rows | Layout | Devices | Timestamp | Validation |
|---|---:|---:|---|---:|---|---|
| `Plant_1_Generation_Data.csv` | 7 | 68,778 | long | 22 | unresolved, `DD-MM-YYYY HH:MM` | warning: 0 fail, 2 warning, 3 pass, 2 not checked |
| `Inverter SCADA.csv` | 9 | 34,560 | long | 8 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 3 warning, 2 pass, 2 not checked |
| `Grid export data.csv` | 9 | 34,560 | long | 8 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 2 warning, 3 pass, 2 not checked |
| `Meteorological data.csv` | 13 | 25,920 | long | 3 stations | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 2 warning, 3 pass, 2 not checked |
| `data_Atersa.csv` | 24 | 51,921 | single | 0 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 5 warning, 3 pass, 2 not checked |
| `data_JaSolar3.csv` | 24 | 51,921 | single | 0 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 4 warning, 3 pass, 2 not checked |
| `data_NingboSolar.csv` | 24 | 51,921 | single | 0 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 5 warning, 3 pass, 2 not checked |
| `data_Photowatt.csv` | 24 | 51,921 | single | 0 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 6 warning, 2 pass, 2 not checked |
| `data_TrinaSolar.csv` | 24 | 51,921 | single | 0 | unresolved, `YYYY-MM-DD HH:MM:SS` | warning: 0 fail, 5 warning, 3 pass, 2 not checked |

Observed issues handled during these checks:

- Mendeley inverter, grid and meteorological files use a long layout; timestamp equality across devices is not a duplicate and is now checked per device.
- The meteorological file uses `station_id`; three weather stations are detected and validated separately.
- Zenodo files retain all 24 source columns. Several columns are entirely empty in the files and are preserved as all-missing rather than dropped.
- Common PV abbreviations such as `temp mod`, `amb temp` and `pmpp` are recognized from the vocabulary.

## Warnings and limitations

- Naive timestamps are not assumed to be UTC. Real files without explicit time-zone evidence remain unresolved for time-zone purposes; UTC-dependent checks are then skipped or limited.
- Unitless numeric columns remain unresolved by design. For example, the Kaggle AC/DC power and yield columns require unit context or an explicit configuration decision before conversion.
- Generic or unrecognized headers remain unresolved; their count is reported in the mapping manifest.
- Night-time generation checks require location/time-zone context and are not run automatically without it.
- Capacity checks require configured capacities; no plant capacity or inverter count is hardcoded.
- If structural device detection finds multiple plausible device columns, it leaves them unresolved rather than choosing silently.
- The synthetic demo's flatline and missing-value warnings are fixture artifacts, not evidence of a real plant fault.
- The real-file checks show compatibility only. They do not establish model accuracy, energy savings or financial impact.
- Runtime environment was Python 3.13.7 with pandas 3.0.1 and openpyxl 3.1.5. The code targets Python 3.11-compatible APIs. `pvlib` and `lightgbm` were not installed; Stage 1 tests do not require them.
- No forecasting, baseline, anomaly, attribution or recovery stage has been implemented yet.

## Exact commands used

From `D:\Storage\Downloads\globathon_models\ML-models`:

```text
python -m pytest -q
python scripts\stage1_demo.py
```

Full demo manifest:

```text
artifacts/stage1_demo/manifest.json
```

The `artifacts/` and `data/` contents are local and git-ignored, except for the documented registry in `data/README.md`.
