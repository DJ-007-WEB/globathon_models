// Typed wrappers for every backend route used by the UI (verified in backend/main.py).
import { apiFetch } from "./client";
import type { AnalysisDetail, AnalysisList, AuthResponse, ChatAnswer, ChatMessage, Plant, Ready, User } from "../types/backend";

export const getReady = () => apiFetch<Ready>("/ready", { auth: false, timeoutMs: 15000 });

export const register = (payload: { email: string; password: string; name: string; business_name: string }) =>
  apiFetch<AuthResponse>("/api/v1/auth/register", { method: "POST", body: JSON.stringify(payload), auth: false, timeoutMs: 15000 });
export const login = (payload: { email: string; password: string }) =>
  apiFetch<AuthResponse>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(payload), auth: false, timeoutMs: 15000 });
export const me = () => apiFetch<User>("/api/v1/auth/me", { timeoutMs: 15000 });

export const listPlants = () => apiFetch<{ items: Plant[] }>("/api/v1/plants", { timeoutMs: 15000 });
export const createPlant = (payload: Plant) =>
  apiFetch<Plant>("/api/v1/plants", { method: "POST", body: JSON.stringify(payload), timeoutMs: 15000 });

export function listAnalyses(params: { plantId?: string; limit?: number; offset?: number } = {}) {
  const query = new URLSearchParams({ limit: String(params.limit ?? 50), offset: String(params.offset ?? 0) });
  if (params.plantId) query.set("plant_id", params.plantId);
  return apiFetch<AnalysisList>(`/api/v1/analyses?${query}`);
}
export const getAnalysis = (requestId: string) => apiFetch<AnalysisDetail>(`/api/v1/analyses/${encodeURIComponent(requestId)}`);
export const getChat = (requestId: string) =>
  apiFetch<{ request_id: string; messages: ChatMessage[] }>(`/api/v1/analyses/${encodeURIComponent(requestId)}/chat`, { timeoutMs: 15000 });
export const askChat = (requestId: string, question: string) =>
  apiFetch<ChatAnswer>(`/api/v1/analyses/${encodeURIComponent(requestId)}/chat`, { method: "POST", body: JSON.stringify({ question }), timeoutMs: 300000 });
