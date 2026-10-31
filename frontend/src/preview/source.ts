// Read-only synthetic preview: generated scenarios processed by the real ML pipeline
// (ml-service/scripts/export_preview_reports.py). No AI narrative is included.
import type { AnalysisDetail, AnalysisSummary, Plant } from "../types/backend";

interface PreviewIndex { plants: Plant[]; analyses: AnalysisSummary[] }
let indexPromise: Promise<PreviewIndex> | null = null;
const detailCache = new Map<string, Promise<AnalysisDetail>>();

const load = <T,>(path: string): Promise<T> => fetch(path).then((response) => {
  if (!response.ok) throw new Error("Synthetic preview data could not be loaded.");
  return response.json() as Promise<T>;
});

export const previewIndex = () => (indexPromise ??= load<PreviewIndex>("/preview/index.json"));
export function previewDetail(requestId: string): Promise<AnalysisDetail> {
  if (!detailCache.has(requestId)) detailCache.set(requestId, load<AnalysisDetail>(`/preview/${encodeURIComponent(requestId)}.json`));
  return detailCache.get(requestId)!;
}
