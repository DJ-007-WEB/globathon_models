// Workspace data: plants, saved analyses, service readiness and the selected plant.
// One provider serves both the live backend (`/app`) and the read-only synthetic preview (`/preview`).
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as api from "../api/endpoints";
import { previewDetail, previewIndex } from "../preview/source";
import type { AnalysisDetail, AnalysisSummary, Plant, Ready } from "../types/backend";

export type WorkspaceMode = "live" | "preview";

interface WorkspaceValue {
  mode: WorkspaceMode;
  base: string;
  plants: Plant[];
  plantsLoading: boolean;
  plantsError: string;
  selectedPlantId: string;
  selectedPlant: Plant | undefined;
  selectPlant: (plantId: string) => void;
  analyses: AnalysisSummary[];
  analysesLoading: boolean;
  analysesError: string;
  refreshPlants: () => Promise<void>;
  refreshAnalyses: () => Promise<void>;
  getDetail: (requestId: string) => Promise<AnalysisDetail>;
  rememberDetail: (detail: AnalysisDetail) => void;
  ready: Ready | null;
  readyState: "checking" | "ready" | "warming" | "ai-error" | "ai-offline" | "offline" | "preview";
  refreshReady: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);
const PLANT_KEY = "solarsleuth_selected_plant";

export function WorkspaceProvider({ mode, children }: { mode: WorkspaceMode; children: ReactNode }) {
  const [plants, setPlants] = useState<Plant[]>([]);
  const [plantsLoading, setPlantsLoading] = useState(true);
  const [plantsError, setPlantsError] = useState("");
  const [selectedPlantId, setSelectedPlantId] = useState<string>(() => {
    try { return mode === "live" ? localStorage.getItem(PLANT_KEY) || "" : ""; } catch { return ""; }
  });
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [analysesLoading, setAnalysesLoading] = useState(true);
  const [analysesError, setAnalysesError] = useState("");
  const [ready, setReady] = useState<Ready | null>(null);
  const [readyState, setReadyState] = useState<WorkspaceValue["readyState"]>(mode === "preview" ? "preview" : "checking");
  const details = useRef(new Map<string, Promise<AnalysisDetail>>());

  const refreshPlants = useCallback(async () => {
    setPlantsLoading(true); setPlantsError("");
    try {
      const items = mode === "preview" ? (await previewIndex()).plants : (await api.listPlants()).items;
      setPlants(items);
      setSelectedPlantId((current) => (current && items.some((plant) => plant.plant_id === current) ? current : items[0]?.plant_id || ""));
    } catch (error) {
      setPlantsError(error instanceof Error ? error.message : "Plants could not be loaded.");
    } finally { setPlantsLoading(false); }
  }, [mode]);

  const refreshAnalyses = useCallback(async () => {
    setAnalysesLoading(true); setAnalysesError("");
    try {
      // All plants are loaded once; screens filter by the selected plant where the design scopes them.
      const items = mode === "preview" ? (await previewIndex()).analyses : (await api.listAnalyses({ limit: 100 })).items;
      setAnalyses(items);
    } catch (error) {
      setAnalysesError(error instanceof Error ? error.message : "Saved analyses could not be loaded.");
    } finally { setAnalysesLoading(false); }
  }, [mode]);

  const refreshReady = useCallback(async () => {
    if (mode === "preview") return;
    try {
      const value = await api.getReady();
      setReady(value);
      setReadyState(
        !value.ml_service_reachable ? "offline"
          : !value.llm_api_reachable ? "ai-offline"
          : value.model_loaded && value.llm_status === "ready" ? "ready"
          : value.llm_status === "not_ready" ? "ai-error"
          : "warming");
    } catch {
      setReady(null); setReadyState("offline");
    }
  }, [mode]);

  useEffect(() => { void refreshPlants(); void refreshAnalyses(); }, [refreshPlants, refreshAnalyses]);
  useEffect(() => {
    if (mode === "preview") return;
    void refreshReady();
    const id = window.setInterval(() => void refreshReady(), 30000);
    return () => window.clearInterval(id);
  }, [mode, refreshReady]);

  const selectPlant = useCallback((plantId: string) => {
    setSelectedPlantId(plantId);
    if (mode === "live") { try { localStorage.setItem(PLANT_KEY, plantId); } catch { /* ignore */ } }
  }, [mode]);

  const getDetail = useCallback((requestId: string) => {
    const cache = details.current;
    if (!cache.has(requestId)) {
      const promise = mode === "preview" ? previewDetail(requestId) : api.getAnalysis(requestId);
      promise.catch(() => cache.delete(requestId));
      cache.set(requestId, promise);
    }
    return cache.get(requestId)!;
  }, [mode]);

  const rememberDetail = useCallback((detail: AnalysisDetail) => {
    details.current.set(detail.request_id, Promise.resolve(detail));
    setAnalyses((current) => [detail, ...current.filter((item) => item.request_id !== detail.request_id)]);
  }, []);

  const value = useMemo<WorkspaceValue>(() => ({
    mode, base: mode === "preview" ? "/preview" : "/app",
    plants, plantsLoading, plantsError, selectedPlantId,
    selectedPlant: plants.find((plant) => plant.plant_id === selectedPlantId),
    selectPlant, analyses, analysesLoading, analysesError, refreshPlants, refreshAnalyses,
    getDetail, rememberDetail, ready, readyState, refreshReady,
  }), [mode, plants, plantsLoading, plantsError, selectedPlantId, selectPlant, analyses, analysesLoading, analysesError,
       refreshPlants, refreshAnalyses, getDetail, rememberDetail, ready, readyState, refreshReady]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}

/** Load one saved analysis (cached) with loading and error state. */
export function useAnalysisDetail(requestId: string | undefined) {
  const { getDetail } = useWorkspace();
  const [state, setState] = useState<{ detail: AnalysisDetail | null; loading: boolean; error: string }>({ detail: null, loading: Boolean(requestId), error: "" });
  useEffect(() => {
    if (!requestId) { setState({ detail: null, loading: false, error: "" }); return; }
    let active = true;
    setState((current) => ({ detail: current.detail?.request_id === requestId ? current.detail : null, loading: true, error: "" }));
    getDetail(requestId)
      .then((detail) => { if (active) setState({ detail, loading: false, error: "" }); })
      .catch((error) => { if (active) setState({ detail: null, loading: false, error: error instanceof Error ? error.message : "The report could not be loaded." }); });
    return () => { active = false; };
  }, [requestId, getDetail]);
  return state;
}
