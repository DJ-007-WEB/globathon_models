# SolarSleuth deterministic ML service

Private FastAPI service on `127.0.0.1:8002`. This service is the sole numerical authority for ingestion, validation, energy metrics, anomalies, hypotheses and evidence.

## Start (PowerShell)

From this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8002 --reload
```

## API

- `GET /health`: liveness
- `GET /ready`: pipeline readiness
- `POST /api/v1/analyze`: one CSV/XLSX operating-data file (called by backend only)

The backend sends `X-Service-Token`; configure the same `INTERNAL_SERVICE_TOKEN` in backend, ML and LLM services. Do not expose this service directly to the browser.

## Pipeline contract

The API delegates to the existing deterministic pipeline: ingestion, schema mapping, unit interpretation, data-quality validation, physics baseline, anomaly detection, evidence-based attribution, reconciled energy waterfall and strict output contract. Do not replace missing metrics with guesses or treat hypotheses as confirmed equipment faults. LLM explanations do not change the ML response.

The HTTP adapter accepts one operating-data file. Additional context-file support in the Python pipeline is not exposed through this endpoint.

## Enriched inverter telemetry schema

The mapper explicitly recognizes the enriched long-format export used for
integration checks. Its columns include `scenario_id`, `synthetic`,
`timestamp_utc`, `inverter_id`, AC/DC power, interval energy, module and
ambient temperature, POA/GHI/DNI/DHI irradiance, rated AC/DC power,
inverter efficiency, DC/AC ratio, temperature coefficient, system losses,
site coordinates, solar elevation and cloud-cover fraction.

A long-format file may contain one row per inverter per timestamp. The
inverter identifier is retained as the device key; timestamp cadence is
derived independently for each inverter. DNI/DHI and cloud-cover values are
mapped as auxiliary telemetry and do not silently replace POA irradiance in
the physics baseline. Scenario identifiers and the synthetic-data marker
are metadata, not plant measurements.

The supplied example contains 768 rows, four inverters, 192 UTC timestamps
at 15-minute intervals over two days, and no missing or duplicate
inverter/timestamp records. Its `synthetic=True` marker means it is suitable
for schema, integration and arithmetic regression checks, not for claims
about real-world forecast or fault-detection accuracy.

## Tests

```powershell
python -m pytest -q
```

The suite covers the pipeline, API boundary, contract, schema mapping, validation and energy calculations. Synthetic benchmarks are not real-world accuracy claims.
