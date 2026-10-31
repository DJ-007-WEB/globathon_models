# Frontend reconstruction plan

Authorities: the reference recording (visual), the existing repository (technical), the backend contracts (data).
See `REFERENCE_VIDEO_ANALYSIS.md` for the frame inventory.

## 1. Existing architecture (before)

- React 19 + Vite 6 + TypeScript 5.8, no router, no state library; one `App.tsx` (~700 lines) holding every
  screen through a `page` state, four CSS files (`style.css`, `views.css`, `demo.css`, `app-extra.css`).
- Backend (FastAPI, port 8001) is the only browser-facing service. Routes verified in `backend/main.py`:
  `GET /health`, `GET /ready`, `POST /api/v1/auth/{register,login}`, `GET /api/v1/auth/me`,
  `GET|POST /api/v1/plants`, `POST /api/v1/analyze/upload` (operating `file` + optional `weather_file`,
  `forecast_file`, `devices_file`, `event_log_file`; `plant_id`, `mode`, `timezone`, `interval_minutes`,
  `sheet_name`), `GET /api/v1/analyses`, `GET /api/v1/analyses/{id}`, `GET|POST /api/v1/analyses/{id}/chat`,
  `POST /api/v1/analyses/{id}/chat/stream` (SSE). `PATCH /plants` exists but CORS blocks it.
- Behaviours that must survive: JWT in `localStorage` (`solarsleuth_access_token`), theme key
  `solarsleuth_theme`, API base override `?api=` / `solarsleuth_api_base`, XHR upload with real progress,
  multi-file upload with role routing by name, SSE chat with non-stream fallback, deterministic-fallback labelling,
  report printing.

## 2. Video page inventory → routes

| Reference | Route |
|---|---|
| Home | `/` |
| Capabilities | `/capabilities` |
| Trust | `/trust` |
| Demo (nav item) | `/demo` |
| Resources | `/resources`, `/resources/:slug` |
| About | `/about` |
| Contact | `/contact` |
| Auth modal | overlay on any route (`?auth=signin|signup`) |
| Workspace | `/app`, `/app/upload`, `/app/reports`, `/app/reports/:requestId`, `/app/assistant`, `/app/plants`, `/app/validation` |
| Synthetic preview | same workspace routes with `/preview` prefix (`/preview`, `/preview/reports`, …) |

## 3. Component mapping

| Layer | Folder | Contents |
|---|---|---|
| App | `src/app` | router, providers, auth gate |
| Design system | `src/design` | `Logo`, `Icon`, `Button`, `Reveal`, `Accordion`, `Modal`, `StatusPill` |
| Marketing | `src/marketing` | `layout/` (header, footer, progress line), `sections/`, `pages/` |
| Workspace | `src/workspace` | `layout/` (sidebar, top bar), `pages/`, `report/` (ML report blocks, AI panel, chat) |
| Charts | `src/charts` | `Waterfall`, `QualityBar` — layout scale only, no analytics |
| API | `src/api` | `client.ts` (fetch + errors), `endpoints.ts`, `upload.ts` (XHR), `chat.ts` (SSE) |
| Types | `src/types` | `ml.ts` (contract v2.1.0), `backend.ts` (envelopes) |
| State | `src/state` | `AuthContext`, `ThemeContext`, `WorkspaceContext` (data source: live API or preview) |
| Lib | `src/lib` | `format.ts` (null-safe formatting, true minus) |
| Content | `src/content` | marketing copy (facts verified in the repository) |
| Preview | `src/preview` | loader for `public/preview/*.json` (real ML output on generated scenarios) |

## 4. Asset mapping

All photography is generated in-repo by `scripts/render-assets.mjs` (three.js, headless Chromium) because no
third-party image host is reachable from the build environment and the reference's stock photos are not ours.
See `ASSET_AUDIT.md`.

## 5. Design tokens

Sampled from the recording (estimated): header/sidebar `#13231A`, deep section `#0F2016`, royal/indigo
`#2B2D8E` (footer) and `#2E3192`/`#33338F` (headings, buttons), lime `#C6F135`, mist `#F4F5F2`, navy card
`#13132E`, success `#2E7D32`, warning `#A16207`, danger `#B42318`. Fonts: Inter (body/UI) and
Manrope (display; closest available match to the reference's geometric bold sans). Tokens live in
`src/styles/tokens.css` with a dark theme under `[data-theme="dark"]`.

## 6. Animation inventory

See `ANIMATION_SPEC.md` (hero entrance, reveals, pipeline auto-advance with pause, marquee, FAQ accordion,
card hovers, page transitions, modal, progress line, chart draw-in, skeletons).

## 7. API integration mapping

| Screen | Calls |
|---|---|
| Auth modal | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Top bar status | `GET /ready` (on mount, every 30 s, manual) |
| Plant selector, Plants | `GET /plants`, `POST /plants` |
| Overview, Reports, Validation, AI | `GET /analyses?plant_id&limit&offset`, `GET /analyses/{id}` (lazy) |
| Upload | `POST /analyze/upload` (XHR multipart) |
| AI explanation | `GET /analyses/{id}/chat`, `POST /analyses/{id}/chat/stream` → fallback `POST …/chat` |

## 8. Implementation sequence

1. Foundation: router, tokens, fonts, design components, API/types/state (keeps the build green).
2. Generated photography and preview fixtures.
3. Marketing layout and pages in reference order.
4. Workspace shell and pages, porting every existing behaviour from `App.tsx`.
5. Remove the legacy `App.tsx` and CSS once replacements pass.
6. QA: live E2E against the four services, screenshots (light/dark, 5 widths), tests, docs.

## 9. Testing strategy

Vitest unit tests for formatting and null handling; Playwright journeys (register → plant → upload → report →
chat → validation → theme persistence) against the real backend/ML with the scripted-LLM harness in
`scripts/e2e/`; responsive screenshots at 320/390/810/1024/1440; `tsc --noEmit` + production build.
