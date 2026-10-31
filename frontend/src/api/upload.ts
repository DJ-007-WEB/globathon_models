// Multipart upload with real progress (fetch cannot report upload progress).
import { getApiBase, getToken, messageFor, ApiError, TUNNEL_HEADERS } from "./client";
import type { AnalyzeResponse } from "../types/backend";

export interface UploadFiles { operating: File; weather?: File | null; forecast?: File | null; devices?: File | null; events?: File | null }
export interface UploadOptions { plantId: string; mode: string; timezone?: string; intervalMinutes?: string; sheetName?: string }

export function uploadAnalysis(files: UploadFiles, options: UploadOptions, handlers: {
  onProgress: (fraction: number) => void; onUploaded: () => void; signal?: AbortSignal;
}): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("file", files.operating);
  if (files.weather) form.append("weather_file", files.weather);
  if (files.forecast) form.append("forecast_file", files.forecast);
  if (files.devices) form.append("devices_file", files.devices);
  if (files.events) form.append("event_log_file", files.events);
  form.append("plant_id", options.plantId.trim() || "unknown-plant");
  form.append("mode", options.mode);
  if (options.timezone?.trim()) form.append("timezone", options.timezone.trim());
  if (options.intervalMinutes?.trim()) form.append("interval_minutes", options.intervalMinutes.trim());
  if (options.sheetName?.trim()) form.append("sheet_name", options.sheetName.trim());

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", getApiBase() + "/api/v1/analyze/upload");
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", "Bearer " + token);
    for (const [key, value] of Object.entries(TUNNEL_HEADERS)) xhr.setRequestHeader(key, value);
    xhr.timeout = 540000;
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) handlers.onProgress(event.loaded / event.total); };
    xhr.upload.onload = () => { handlers.onProgress(1); handlers.onUploaded(); };
    xhr.onload = () => {
      let body: any = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON error page */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        if (!body?.ml_analysis) reject(new ApiError(502, "The backend response did not include the deterministic ML result."));
        else resolve(body as AnalyzeResponse);
      } else {
        reject(new ApiError(xhr.status, typeof body?.detail === "string" ? body.detail : messageFor(xhr.status)));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, messageFor(0)));
    xhr.ontimeout = () => reject(new ApiError(0, "The analysis timed out. The local AI model may still be warming up; retry shortly."));
    xhr.onabort = () => reject(new ApiError(-1, "Upload cancelled. If the file had already been sent, the analysis may still complete — check Reports."));
    handlers.signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

/** Route several dropped files to upload slots by name; the ML service re-checks every file by content. */
export function assignFilesByName(list: File[]): UploadFiles | null {
  const role = (name: string) => {
    const n = name.toLowerCase();
    if (/weather|meteo|climate/.test(n)) return "weather";
    if (/forecast|design|expected|pvsyst|simulation/.test(n)) return "forecast";
    if (/event|alarm|log/.test(n)) return "events";
    if (/device|inverter_list|equipment|asset/.test(n)) return "devices";
    return "operating";
  };
  const operating = list.filter((file) => role(file.name) === "operating");
  const main = operating.find((file) => file.name.toLowerCase().endsWith(".xlsx")) || operating[0] || (list.length === 1 ? list[0] : undefined);
  if (!main) return null;
  const result: UploadFiles = { operating: main };
  for (const file of list) {
    if (file === main) continue;
    const r = role(file.name);
    if (r === "weather") result.weather = file;
    else if (r === "forecast") result.forecast = file;
    else if (r === "events") result.events = file;
    else if (r === "devices") result.devices = file;
  }
  return result;
}
