import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useWorkspace } from "../../state/WorkspaceContext";
import { assignFilesByName, uploadAnalysis, type UploadFiles } from "../../api/upload";
import { Card, Empty, PageHead } from "../ui";

type Stage = "idle" | "uploading" | "processing" | "complete" | "failed";
const SLOTS: Array<{ key: keyof UploadFiles; label: string; hint: string }> = [
  { key: "operating", label: "Operating data", hint: "Required · power or energy per device with timestamps" },
  { key: "weather", label: "Weather", hint: "Optional · irradiance and temperature" },
  { key: "forecast", label: "Forecast", hint: "Optional · completes the waterfall" },
  { key: "devices", label: "Devices", hint: "Optional · inverter list and capacities" },
  { key: "events", label: "Event log", hint: "Optional · alarms that can confirm hypotheses" },
];
const MODES = [
  { value: "auto", title: "Automatic", body: "Detects a time series or a single snapshot." },
  { value: "full", title: "Full time-series", body: "Validation, baseline, anomalies, waterfall." },
  { value: "snapshot", title: "Snapshot", body: "One reading per device; limited metrics." },
];
const STEPS = ["Upload", "Validate / map", "ML analysis", "AI explanation", "Report ready"];

export function Upload() {
  const { mode, base, plants, selectedPlantId, selectPlant, rememberDetail, refreshAnalyses } = useWorkspace();
  const navigate = useNavigate();
  const [files, setFiles] = useState<Partial<UploadFiles>>({});
  const [analysisMode, setAnalysisMode] = useState("auto");
  const [timezone, setTimezone] = useState("");
  const [interval, setInterval_] = useState("");
  const [sheet, setSheet] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [fraction, setFraction] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = stage === "uploading" || stage === "processing";

  useEffect(() => {
    if (stage !== "processing") return;
    const start = Date.now();
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - start) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [stage]);

  if (mode === "preview") return (<><PageHead eyebrow="Upload & Analyse" title="Upload & Analyse" />
    <Card><Empty icon="upload" title="Uploads are disabled in the synthetic preview" body="Create a workspace to analyse your own CSV or XLSX export."
      action={<Link className="btn btn-royal" to="/app">Open your workspace</Link>} /></Card></>);

  if (!plants.length) return (<><PageHead eyebrow="Upload & Analyse" title="Upload & Analyse" />
    <Card><Empty icon="plant" title="Register a plant first" body="Every upload belongs to a plant." action={<Link className="btn btn-royal" to={`${base}/plants`}>Register a plant</Link>} /></Card></>);

  const addFiles = (list: File[]) => {
    const accepted = list.filter((f) => /\.(csv|xlsx)$/i.test(f.name));
    if (accepted.length < list.length) setError("Only CSV and XLSX files are supported; other files were ignored.");
    else setError("");
    if (!accepted.length) return;
    if (accepted.length === 1 && files.operating) { setFiles((cur) => ({ ...cur, ...assignFilesByName([...Object.values(cur).filter(Boolean) as File[], accepted[0]]) })); return; }
    const assigned = assignFilesByName(accepted);
    if (assigned) setFiles((cur) => ({ ...cur, ...assigned }));
  };
  const onDrop = (event: DragEvent) => { event.preventDefault(); setDrag(false); if (!busy) addFiles(Array.from(event.dataTransfer.files)); };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!files.operating) { setError("Add an operating-data file."); return; }
    setError(""); setStage("uploading"); setFraction(0); setElapsed(0);
    abort.current = new AbortController();
    try {
      const result = await uploadAnalysis(files as UploadFiles, { plantId: selectedPlantId, mode: analysisMode, timezone, intervalMinutes: interval, sheetName: sheet },
        { onProgress: setFraction, onUploaded: () => setStage("processing"), signal: abort.current.signal });
      setStage("complete");
      rememberDetail({ request_id: result.request_id, plant_id: result.plant_id, filename: files.operating.name,
        analysis_status: result.ml_analysis?.analysis_status ?? "success", analysis_mode: result.analysis_mode, created_at: new Date().toISOString(), result });
      void refreshAnalyses();
      window.setTimeout(() => navigate(`${base}/reports/${encodeURIComponent(result.request_id)}`), 700);
    } catch (err) {
      setStage("failed");
      setError(err instanceof Error ? err.message : "The analysis failed.");
    }
  }

  const stepState = (i: number) => {
    if (stage === "complete") return "done";
    if (i === 0) return stage === "uploading" ? "active" : stage === "failed" && fraction < 1 ? "failed" : "done";
    if (i <= 3) return stage === "processing" ? "active" : stage === "failed" && fraction >= 1 ? "failed" : "pending";
    return "pending";
  };

  return (
    <>
      <PageHead eyebrow="Upload & Analyse" title="Analyse an export" body="The deterministic ML service computes every number; the local AI then explains the result." />
      <form onSubmit={submit} className="upload-grid">
        <div className="upload-main">
          <Card title="Files" icon="file-in">
            <div className={`dropzone ${drag ? "drag" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
              onClick={() => !busy && inputRef.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}>
              <Icon name="upload" size={28} />
              <b>Drop CSV or XLSX files here, or browse</b>
              <small className="muted">Several files at once are routed by name (weather, forecast, devices, events); the ML service re-checks each by content. Up to 25 MiB each.</small>
              <input ref={inputRef} type="file" accept=".csv,.xlsx" multiple hidden onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }} />
            </div>
            <ul className="slots">
              {SLOTS.map((slot) => {
                const file = files[slot.key];
                return (
                  <li key={slot.key} className={file ? "filled" : ""}>
                    <Icon name={file ? "check" : "file-in"} size={16} />
                    <div><b>{slot.label}</b><small className="muted">{file ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB` : slot.hint}</small></div>
                    {file ? <button type="button" className="icon-btn ws-icon-btn" aria-label={`Remove ${slot.label} file`} disabled={busy} onClick={() => setFiles((cur) => ({ ...cur, [slot.key]: undefined }))}><Icon name="x" size={16} /></button>
                      : <label className="btn btn-outline btn-sm">Choose<input type="file" accept=".csv,.xlsx" hidden disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) setFiles((cur) => ({ ...cur, [slot.key]: f })); e.target.value = ""; }} /></label>}
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card title="Analysis mode" icon="layers">
            <div className="mode-cards" role="radiogroup">
              {MODES.map((m) => (
                <label key={m.value} className={`mode-card ${analysisMode === m.value ? "active" : ""}`}>
                  <input type="radio" name="mode" value={m.value} checked={analysisMode === m.value} onChange={() => setAnalysisMode(m.value)} disabled={busy} />
                  <b>{m.title}</b><small className="muted">{m.body}</small>
                </label>
              ))}
            </div>
          </Card>
        </div>
        <div className="upload-side">
          <Card title="Settings" icon="plant">
            <div className="form">
              <label>Plant<select className="select" value={selectedPlantId} onChange={(e) => selectPlant(e.target.value)} disabled={busy}>{plants.map((p) => <option key={p.plant_id} value={p.plant_id}>{p.name}</option>)}</select></label>
              <label>Timezone <small className="muted">optional</small><input placeholder="e.g. Asia/Kolkata" value={timezone} onChange={(e) => setTimezone(e.target.value)} disabled={busy} /></label>
              <label>Interval (minutes) <small className="muted">optional</small><input inputMode="numeric" placeholder="Detected automatically" value={interval} onChange={(e) => setInterval_(e.target.value)} disabled={busy} /></label>
              <label>Sheet name <small className="muted">XLSX, optional</small><input placeholder="Detected automatically" value={sheet} onChange={(e) => setSheet(e.target.value)} disabled={busy} /></label>
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="upload-actions">
              <button type="submit" className="btn btn-royal" disabled={busy || !files.operating}>{busy ? <span className="spinner" /> : <Icon name="sparkle" />}Run analysis</button>
              {busy && <button type="button" className="btn btn-outline" onClick={() => abort.current?.abort()}>Cancel</button>}
            </div>
          </Card>
          {stage !== "idle" && (
            <Card title="Progress" icon="pulse">
              <ol className="steps" role="status" aria-live="polite">
                {STEPS.map((label, i) => <li key={label} className={`step-${stepState(i)}`}><span>{stepState(i) === "done" ? <Icon name="check" size={13} /> : stepState(i) === "failed" ? "!" : i + 1}</span>{label}</li>)}
              </ol>
              {stage === "uploading" && <div className="progress"><i style={{ width: `${Math.round(fraction * 100)}%` }} /></div>}
              <p className="ws-foot">{stage === "uploading" ? `Uploading… ${Math.round(fraction * 100)}%` : stage === "processing" ? `Validating, running deterministic ML and generating the local AI explanation · ${elapsed}s. Local CPU inference can take a few minutes.` : stage === "complete" ? "Report ready — opening it now." : "The analysis could not be completed."}</p>
            </Card>
          )}
        </div>
      </form>
    </>
  );
}
