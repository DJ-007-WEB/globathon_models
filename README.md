# SolarSleuth — Solar Recovery Intelligence Frontend

React + Vite frontend for the Globathon 2026 Solar Recovery Intelligence project. The visual design is based on the existing [SolarSleuth frontend in DJ-007-WEB/globathon](https://github.com/DJ-007-WEB/globathon), adapted to call the local application backend and render its LLM-generated analysis.

## Run locally

Prerequisites: Node.js and npm.

```powershell
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://127.0.0.1:5173`).

## Start the services

Keep these services running in separate terminals:

1. Local LLM API on `http://127.0.0.1:8000`.
2. Application backend on `http://127.0.0.1:8001`.
3. Frontend via `npm run dev` on port `5173`.

The frontend calls only the application backend. It does not call the model directly and does not perform ML calculations in the browser.

## Demo access

- Email: `demo@solarsleuth.app`
- Password: `Demo@1234`

Authentication is a **local demo gate only**; it is not production authentication and does not protect sensitive data.

## Backend integration

- `GET /ready` — readiness status and model-loaded indicator.
- `POST /api/v1/analyze` — sends plant context and observations to the backend, which forwards them to the local LLM.

The API base defaults to `http://127.0.0.1:8001`. To use another backend, either open the frontend with `?api=http://127.0.0.1:8001` or change the Backend API URL in the workspace and press **Connect**. The value is remembered in local browser storage.

The analysis form sends the entered plant identifier, capacity context, current power, expected power, panel temperature and irradiance. The UI renders the returned summary, observations, possible causes, supporting evidence, recommended checks, limitations and confidence. Missing sections are explicitly shown as missing rather than invented.

## Build

```powershell
npm run build
npm run preview
```

## Important limitations

- The LLM output is an explanation, not proof of a physical fault. Verify hypotheses against telemetry and qualified operator checks.
- The response renderer preserves the model's returned content but does not independently validate whether its claims are factually correct.
- The demo sign-in is browser-local only.
- The frontend branch is independent from the `backend`, `AI-model`, and `ML_models` branches. No model-training or ML implementation files are changed here.
