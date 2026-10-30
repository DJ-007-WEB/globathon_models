# SolarSleuth — React + Vite Frontend

The frontend runs on **127.0.0.1:5173** and communicates only with the application backend on port 8001. It never calls the ML or LLM service directly and performs no plant-energy calculations. Workspace navigation is limited to Overview, Upload & analyse, Reports, and AI explanation.

## Run

```powershell
npm install
npm run dev
```

The Vite script is pinned to port 5173 and fails rather than silently choosing another port.

## Data workflows

- **Dataset upload:** CSV/XLSX file upload to `POST /api/v1/analyze/upload`. Options include plant ID, auto/snapshot/full mode, optional IANA timezone, sampling interval and Excel sheet name.
- **File-only workflow:** plant measurements are supplied through CSV/XLSX uploads. Manual measurement entry is not part of the operational workflow.
- **Response:** uploaded-data responses display the complete deterministic ML contract (energy metrics, waterfall, anomalies, hypotheses and limitations) separately from the LLM explanation (summary, observations, possible causes, supporting evidence, technician checks, limitations and confidence).

The current upload UI accepts one operating-data file up to 25 MiB. The Python ML pipeline supports additional context inputs, but the HTTP upload contract does not yet expose separate weather/device/forecast/event-log files. Column mapping and unit interpretation must be validated by the ML service; ambiguous units must not be guessed. See [PROJECT_REQUIREMENTS.md](./PROJECT_REQUIREMENTS.md) for the full architecture, security, UX, report, and acceptance criteria.

## Service startup

Run the four components from separate working copies:

- ML service: `http://127.0.0.1:8002`
- Local LLM API: `http://127.0.0.1:8000`
- Application backend: `http://127.0.0.1:8001`
- Frontend: `http://127.0.0.1:5173`

The backend is the only browser-facing API. Configure its `CORS_ORIGINS` to include `http://127.0.0.1:5173`.

## Demo access and security

- Email: `demo@solarsleuth.app`
- Password: `Demo@1234`

Authentication is a browser-local demo gate only; it is not production authentication and does not protect sensitive data. Do not use it for confidential plant information.

## Build

```powershell
npm run build
npm run preview
```

The repository changes have not been verified by running this build in the target Windows environment yet.
