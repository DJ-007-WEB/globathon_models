# SolarSleuth — Solar Recovery Intelligence Frontend

React + Vite frontend for the Globathon 2026 Solar Recovery Intelligence project.

## Run locally

```powershell
npm install
npm run dev
```

Open the Vite URL (normally `http://127.0.0.1:5173`).

## Services

The frontend calls only the application backend on `http://127.0.0.1:8001`. The backend orchestrates:
1. Private ML service on `http://127.0.0.1:8002` for CSV/XLSX ingestion, validation, deterministic calculations and versioned results.
2. Local LLM API on `http://127.0.0.1:8000` for evidence-grounded natural-language explanation.

The browser never calls the ML or LLM service directly and performs no plant-energy calculations.

## Dataset workflow

Open **Data upload**, select a CSV or XLSX file (maximum 25 MB), provide a plant identifier and optionally timezone / interval metadata, then run analysis.

The UI displays the returned ML energy metrics and limitations separately from the LLM's explanation, observations, possible causes, evidence, recommended checks and confidence. The progress indicator and response entrance are animated; the current API is request/response, not token-streaming.

The original manual-reading workflow remains available and continues to use `POST /api/v1/analyze`.

## Demo access and security

- Demo email: `demo@solarsleuth.app`
- Demo password: `Demo@1234`

Authentication remains a browser-local demo gate. It is **not production authentication** and must not be treated as protection for confidential datasets. Do not expose this prototype publicly with sensitive plant data until real server-side authentication and authorization are implemented.

## Build

```powershell
npm run build
npm run preview
```
