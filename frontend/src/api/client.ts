// Central HTTP client. The browser talks only to the SolarSleuth backend.

const DEFAULT_API = "http://127.0.0.1:8001";
const API_KEY = "solarsleuth_api_base";
const TOKEN_KEY = "solarsleuth_access_token";

/** API base: `?api=` override (remembered), saved override, VITE_API_BASE, then the local default. */
export function getApiBase(): string {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get("api");
    if (fromQuery) {
      localStorage.setItem(API_KEY, fromQuery);
      return fromQuery.replace(/\/$/, "");
    }
    const saved = localStorage.getItem(API_KEY);
    if (saved) return saved.replace(/\/$/, "");
  } catch { /* storage unavailable */ }
  return (import.meta.env.VITE_API_BASE || DEFAULT_API).replace(/\/$/, "");
}

export function setApiBase(value: string): void {
  try { localStorage.setItem(API_KEY, value.replace(/\/$/, "")); } catch { /* ignore */ }
}

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
export function setToken(token: string): void {
  try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** User-facing message for a status code when the backend gave no `detail` string. */
export function messageFor(status: number): string {
  switch (status) {
    case 0: return "Could not reach the backend. Check that it is running and the connection address is correct.";
    case 401: return "Your session expired. Sign in again.";
    case 413: return "Upload exceeds the configured size limit.";
    case 415: return "Only CSV and XLSX files are supported.";
    case 429: return "Analysis capacity is busy. Retry shortly.";
    case 502: case 503: case 504: return "A required local analysis service is unavailable.";
    default: return `The request could not be completed (HTTP ${status}).`;
  }
}

export const SESSION_EXPIRED_EVENT = "solarsleuth:session-expired";

export async function apiFetch<T>(path: string, options: RequestInit & { timeoutMs?: number; auth?: boolean } = {}): Promise<T> {
  const { timeoutMs = 20000, auth = true, headers, ...rest } = options;
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(getApiBase() + path, {
      ...rest,
      headers: { ...(rest.body && !(rest.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
                 ...(auth && token ? { Authorization: `Bearer ${token}` } : {}), ...headers },
      signal: rest.signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") throw new ApiError(0, "The backend did not respond in time.");
    throw new ApiError(0, messageFor(0));
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && auth && token) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    const detail = typeof body?.detail === "string" ? body.detail : messageFor(response.status);
    throw new ApiError(response.status, detail);
  }
  return body as T;
}
