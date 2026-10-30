# SolarSleuth frontend

React 19 + Vite + TypeScript application. Runs at `http://127.0.0.1:5173` and communicates only with the backend at `http://127.0.0.1:8001`.

## Commands

```powershell
npm install
npm run dev
npm run build
npm run preview
```

The Vite dev server uses strict port 5173. Authentication, plants, uploads, saved reports and report-grounded chat are handled through the backend API. The frontend does not call ML/LLM services directly and does not calculate energy metrics.

See the repository-root README for full four-service setup and end-to-end testing.
