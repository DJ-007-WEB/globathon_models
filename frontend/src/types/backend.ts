// Backend envelopes (backend/main.py, backend/schemas.py).
import type { MlResult } from "./ml";

export type Confidence = "low" | "moderate" | "high" | "insufficient_evidence";

export interface Explanation {
  summary: string;
  observations: string[];
  possible_causes: string[];
  supporting_evidence: string[];
  recommended_checks: string[];
  limitations: string[];
  confidence: Confidence;
}

/** Saved analysis result. `analysis` is null only for synthetic preview reports. */
export interface AnalyzeResponse {
  request_id: string;
  plant_id: string;
  model: string;
  analysis: Explanation | null;
  ml_analysis: MlResult | null;
  analysis_mode: string | null;
}

export interface User { user_id: string; name: string; email: string; business_id: string; business_name: string }
export interface AuthResponse { access_token: string; token_type: string; expires_in: number; user: User }

export interface Plant {
  plant_id: string;
  name: string;
  location?: string | null;
  capacity_kw?: number | null;
  timezone?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AnalysisSummary {
  request_id: string;
  plant_id: string;
  filename: string;
  analysis_status: string;
  analysis_mode: string | null;
  created_at: string;
}
export interface AnalysisList { items: AnalysisSummary[]; total: number; limit: number; offset: number }
export interface AnalysisDetail extends AnalysisSummary { result: AnalyzeResponse }

export interface ChatMessage {
  role: "user" | "assistant";
  content: string | Explanation;
  created_at?: string;
  model?: string;
}
export interface ChatAnswer { request_id: string; answer: Explanation; model: string; created_at: string }

export interface Ready {
  status: "ready" | "degraded";
  ml_service_reachable: boolean;
  llm_api_reachable: boolean;
  model_loaded: boolean;
  llm_status?: string;
  llm_error?: string | null;
  llm_model_name?: string | null;
}

/** Models that mean "no local AI narrative": the backend's evidence-only fallback, or a preview report. */
export const FALLBACK_MODELS = new Set(["deterministic-fallback", "unavailable", "none"]);
