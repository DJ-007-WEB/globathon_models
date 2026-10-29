# Dynamic Solar Dataset Ingestion

This module is the first step of the Solar Recovery Intelligence pipeline. It reads an unfamiliar CSV/Excel file, reports its columns and sample rows, suggests possible mappings, and only standardizes data after a mapping is explicitly supplied.

## Install

From the repository root:

```bash
python -m pip install pandas openpyxl
```

For legacy `.xls` files, you may also need `xlrd`.

## Step 1: Inspect an incoming dataset

```bash
python training/solar_ingestion/solar_ingestion.py --input path/to/plant_data.csv --report artifacts/inspection.json
```

Excel (first sheet by default):

```bash
python training/solar_ingestion/solar_ingestion.py --input path/to/plant_data.xlsx --sheet 0 --report artifacts/inspection.json
```

The report includes source column names, a small sample, candidate mappings, and ambiguity flags. Suggestions are heuristics only: they do not establish column meaning, units, timezone, or data quality.

## Step 2: Confirm mappings

Create a mapping JSON file. The source-column values must exactly match the column headers in your file. Do not copy the example column names literally unless they match your dataset.

```json
{
  "columns": {
    "timestamp": "your timestamp column",
    "actual_power": "your measured power column",
    "irradiance": "your irradiance column",
    "inverter_status": "your status column"
  },
  "units": {
    "actual_power": "kW",
    "irradiance": "W/m2"
  },
  "notes": "Confirmed against the dataset documentation"
}
```

Supported canonical concepts: `timestamp`, `plant_id`, `device_id`, `actual_power`, `expected_power`, `energy`, `irradiance`, `inverter_status`, `ambient_temperature`, `module_temperature`, `voltage`, `current`, and `event_code`. These are the internal schema, not assumptions about incoming column names. You can omit fields that are not present. A timestamp mapping is required for time-series standardization.

## Step 3: Standardize after confirming

```bash
python training/solar_ingestion/solar_ingestion.py \
  --input path/to/plant_data.csv \
  --mapping path/to/mapping.json \
  --output artifacts/standardized.jsonl \
  --report artifacts/standardization_report.json
```

Each JSONL record preserves original source columns, the mapped values, the exact mapping used, source row number, and user-supplied units. This supports traceability and later review.

## Safety and data-quality boundaries

- The module does not automatically accept mapping suggestions; the user must supply a mapping file.
- Ambiguous or unknown columns remain unmapped until reviewed.
- Units are recorded, not guessed or converted.
- Timestamps are parsed but timezone is not inferred.
- Duplicate timestamps and invalid timestamps are reported; rows are not silently dropped.
- Missing values are preserved as null; no imputation occurs.
- No anomaly detection, expected-generation calculation, ML inference, or root-cause diagnosis is performed here. Those belong in subsequent pipeline stages.
- Review the inspection report before processing confidential plant data. Do not commit real datasets or reports containing sensitive data.
