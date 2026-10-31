import { useCallback, useEffect, useState, type FormEvent } from "react";

type Analysis = {
  summary: string;
  observations: string[];
  possible_causes: string[];
  supporting_evidence: string[];
  recommended_checks: string[];
  limitations: string[];
  confidence: "low" | "moderate" | "high" | "insufficient_evidence";
};
type MlAnalysis = Record<string, any>;
type ApiResult = { request_id?: string | null; plant_id?: string; model?: string; analysis: Analysis; ml_analysis?: MlAnalysis | null; analysis_mode?: string | null };
type Turn = { id: string; question: string; createdAt: number; result?: ApiResult; error?: string; loading?: boolean };
type ChatMessage = { role: "user" | "assistant"; content: string | Analysis; created_at?: string; model?: string };
type Plant = { plant_id: string; name: string; location?: string | null; capacity_kw?: number | null; timezone?: string | null };
async function loadStoredAnalyses(base: string, token: string): Promise<Turn[]> {
  const headers = { Authorization: "Bearer " + token };
  let response: Response;
  try { response = await fetch(base + "/api/v1/analyses?limit=100&offset=0", { headers, signal: AbortSignal.timeout(20000) }); }
  catch { return []; }
  if (!response.ok) return [];
  const payload = await response.json();
  const items = Array.isArray(payload.items) ? payload.items : [];
  const details = await Promise.all(items.map(async (item: any) => {
    try {
      const detail = await fetch(base + "/api/v1/analyses/" + encodeURIComponent(item.request_id), { headers, signal: AbortSignal.timeout(20000) });
      if (!detail.ok) return null;
      const value = await detail.json();
      if (!value.result?.ml_analysis || !value.result?.analysis) return null;
      return { id: value.request_id, question: "Dataset analysis: " + value.filename,
        createdAt: Date.parse(value.created_at) || Date.now(), result: value.result } as Turn;
    } catch { return null; }
  }));
  return details.filter((item): item is Turn => Boolean(item)).reverse();
}


async function loadPlantHistory(base: string, token: string, plantId: string): Promise<Turn[]> {
  const headers = { Authorization: "Bearer " + token };
  const query = new URLSearchParams({ limit: "100", offset: "0", plant_id: plantId });
  const response = await fetch(base + "/api/v1/analyses?" + query.toString(), {
    headers, signal: AbortSignal.timeout(20000)
  });
  if (!response.ok) throw new Error("Unable to load this plant's analysis history.");
  const payload = await response.json();
  const items = Array.isArray(payload.items) ? payload.items : [];
  const details = await Promise.all(items.map(async (item: any) => {
    try {
      const detail = await fetch(base + "/api/v1/analyses/" + encodeURIComponent(item.request_id), {
        headers, signal: AbortSignal.timeout(20000)
      });
      if (!detail.ok) return null;
      const value = await detail.json();
      if (!value.result?.ml_analysis || !value.result?.analysis) return null;
      return { id: value.request_id, question: "Dataset analysis: " + value.filename,
        createdAt: Date.parse(value.created_at) || Date.now(), result: value.result } as Turn;
    } catch { return null; }
  }));
  return details.filter((item): item is Turn => Boolean(item)).reverse();
}

const energyMetric = (turn: Turn | undefined, key: string): number | null => {
  const value = turn?.result?.ml_analysis?.energy?.[key]?.value_kwh;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};
const formatEnergy = (value: number | null): string =>
  value === null ? "Not reported" : value.toLocaleString(undefined, { maximumFractionDigits: 2 }) + " kWh";

const DEFAULT_API = "http://127.0.0.1:8001";
const getApiBase = () => {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("api");
    if (fromQuery) { localStorage.setItem("solarsleuth_api_base", fromQuery); return fromQuery.replace(/\/$/, ""); }
    return (localStorage.getItem("solarsleuth_api_base") || DEFAULT_API).replace(/\/$/, "");
  } catch { return DEFAULT_API; }
};
const pretty = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const listOrFallback = (items?: string[], fallback = "No details were returned for this section.") =>
  items?.length ? items : [fallback];

function renderSafeMarkdown(source: string) {
  const inline = (value: string) => value.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part
  );
  return source.split(/\r?\n/).map((line, index) => {
    if (line.startsWith("### ")) return <h4 key={index}>{inline(line.slice(4))}</h4>;
    if (line.startsWith("- ")) return <div className="chat-markdown-list-item" key={index}>• {inline(line.slice(2))}</div>;
    if (!line.trim()) return <div className="chat-markdown-spacer" key={index}/>;
    return <p key={index}>{inline(line)}</p>;
  });
}

function BrandMark() {
  return <span className="brand-mark"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 4 5 12.5v15L20 36l15-8.5v-15L20 4Z" fill="none" stroke="currentColor" strokeWidth="1.7"/><path d="M20 10v20M10 15.5l20 9M10 24.5l20-9" stroke="currentColor" strokeWidth="1.5"/><circle cx="20" cy="20" r="4" fill="currentColor"/></svg></span>;
}


function displayValue(value: unknown): string {
  if (value == null || value === "") return "Not reported";
  if (typeof value === "string") return value.replaceAll("_", " ");
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:3}) : "Not reported";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(displayValue).join(" · ");
  if (typeof value === "object") {
    const record=value as Record<string,unknown>;
    const keys=["message","description","reason","label","name","type","status","value","count","timestamp","device_id"];
    const parts=keys.filter(key=>record[key]!=null).map(key=>pretty(key)+": "+displayValue(record[key]));
    return parts.join(" · ") || Object.entries(record).filter(([,v])=>v==null||typeof v!=="object").map(([k,v])=>pretty(k)+": "+displayValue(v)).join(" · ") || "Details available";
  }
  return String(value);
}

function EnergyPerformanceChart({result}:{result:MlAnalysis}) {
  const e=result.energy||{};
  const values=[
    {label:"Forecast",value:e.forecast?.value_kwh??result.forecast_energy,tone:"forecast"},
    {label:"Expected",value:e.expected?.value_kwh??result.expected_energy,tone:"expected"},
    {label:"Actual",value:e.actual?.value_kwh??result.actual_energy,tone:"actual"}
  ].filter(x=>typeof x.value==="number"&&Number.isFinite(x.value)) as Array<{label:string;value:number;tone:string}>;
  if(!values.length)return <p className="chart-empty">No comparable energy totals were returned.</p>;
  const max=Math.max(1,...values.map(x=>Math.abs(x.value)));
  return <div className="visual-chart"><div className="chart-legend">{values.map(x=><span key={x.label}><i className={"legend-"+x.tone}/>{x.label}</span>)}</div>{values.map(x=><div className="hbar-row" key={x.label}><span className="hbar-label">{x.label}</span><div className="hbar-track"><i className={"hbar-fill "+x.tone} style={{width:Math.max(2,Math.abs(x.value)/max*100)+"%"}}/></div><strong>{x.value.toLocaleString(undefined,{maximumFractionDigits:2})} kWh</strong></div>)}<p className="chart-footnote">Source: deterministic ML output. No values are recalculated for this chart.</p></div>;
}

function DevicePerformance({items}:{items:any[]}) {
  if (!items.length) return <p className="chart-empty">No device-level energy totals were returned for this analysis.</p>;
  const fmt=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:2})+" kWh":"Not reported";
  return <div className="device-performance"><div className="device-performance-head"><span>Inverter</span><span>Measured</span><span>Expected</span><span>Difference</span></div>{items.map((item:any)=><div className="device-performance-row" key={String(item.device_id)}><strong>{String(item.device_id||"Unknown device")}</strong><span>{fmt(item.actual_energy_kwh)}</span><span>{fmt(item.expected_energy_kwh)}</span><span className={typeof item.deviation_kwh==="number"?(item.deviation_kwh<0?"device-negative":"device-positive"):""}>{fmt(item.deviation_kwh)}</span></div>)}<p className="chart-footnote">Per-inverter totals from deterministic ML. Differences are supplied by the ML service; the dashboard does not recalculate them.</p></div>;
}

function ValidationBars({checks}:{checks:any[]}) {
  const rows=[
    {label:"Passed",n:checks.filter(x=>["pass","passed","success"].includes(String(x.status||"").toLowerCase())).length,tone:"pass"},
    {label:"Warnings",n:checks.filter(x=>String(x.status||"").toLowerCase()==="warning").length,tone:"warning"},
    {label:"Failed",n:checks.filter(x=>["fail","failed","error"].includes(String(x.status||"").toLowerCase())).length,tone:"fail"}
  ];
  const max=Math.max(1,...rows.map(x=>x.n));
  return <div className="validation-chart">{rows.map(x=><div className="validation-bar-item" key={x.label}><div className="validation-bar-track"><i className={"validation-bar-fill "+x.tone} style={{height:(x.n/max*100)+"%"}}/></div><b>{x.n}</b><small>{x.label}</small></div>)}</div>;
}

function MlAnalysisResponse({result}:{result:MlAnalysis}) {
  const e=result.energy||{},q=result.data_quality||{},w=result.waterfall||{};
  const anomalies=Array.isArray(result.anomalies)?result.anomalies:[];
  const hypotheses=Array.isArray(result.hypotheses)?result.hypotheses:[];
  const evidence=Array.isArray(result.evidence)?result.evidence:[];
  const limits=Array.isArray(result.limitations)?result.limitations:[];
  const fmt=(v:unknown)=>typeof v==="number"&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:2})+" kWh":"Not reported";
  const facts=[["Rows analysed",result.interval?.row_count??q.rows],["Sampling interval",typeof result.interval?.sampling_interval_seconds==="number"?result.interval.sampling_interval_seconds+" seconds":null],["Devices detected",result.interval?.device_count],["Time zone",result.interval?.timezone||result.request?.timezone],["Coverage begins",result.interval?.start_utc],["Coverage ends",result.interval?.end_utc],["Data quality",q.status]];
  return <div className="report-ml">
    <section className="report-section"><div className="section-kicker">01 · DETERMINISTIC ANALYSIS</div><h2>Performance at a glance</h2><p>{result.summary||"Review the measured values and evidence returned by the analysis pipeline."}</p>
      <div className="report-metrics">{[["Forecast energy",e.forecast?.value_kwh??result.forecast_energy],["Expected energy",e.expected?.value_kwh??result.expected_energy],["Actual energy",e.actual?.value_kwh??result.actual_energy],["Energy deviation",e.deviation?.value_kwh??result.deviation]].map(([label,value])=><article key={String(label)}><small>{label}</small><strong>{fmt(value)}</strong></article>)}</div><EnergyPerformanceChart result={result}/>
    </section>
    <section className="report-section"><div className="section-kicker">02 · DATASET PROFILE</div><h2>What was analysed</h2><div className="report-facts">{facts.map(([label,value])=><div key={String(label)}><small>{label}</small><strong>{displayValue(value)}</strong></div>)}</div></section>
    {Array.isArray(result.device_performance)&&result.device_performance.length>0&&<section className="report-section"><div className="section-kicker">03 · DEVICE PERFORMANCE</div><h2>How each inverter performed</h2><p className="report-note">Compare measured energy with the physics-based expected energy for each detected inverter.</p><DevicePerformance items={result.device_performance}/></section>}
    {Object.keys(w).length>0&&<section className="report-section"><div className="section-kicker">03 · ENERGY BREAKDOWN</div><h2>Energy loss breakdown</h2><div className="detail-list">{Object.entries(w).map(([key,value])=><div className="detail-row" key={key}><span>{pretty(key)}</span><strong>{displayValue(value)}</strong></div>)}</div></section>}
    <section className="report-section"><div className="section-kicker">04 · FINDINGS</div><h2>Detected anomalies</h2>{anomalies.length?<ul className="readable-list">{anomalies.slice(0,40).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul>:<p>No anomaly records were returned.</p>}{hypotheses.length>0&&<><h3>Possible contributing factors</h3><p className="report-note">These are hypotheses, not confirmed equipment faults.</p><ul className="readable-list">{hypotheses.slice(0,30).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></>}</section>
    {evidence.length>0&&<section className="report-section"><div className="section-kicker">05 · SUPPORTING EVIDENCE</div><h2>Evidence returned by the pipeline</h2><ul className="readable-list">{evidence.slice(0,40).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></section>}
    {limits.length>0&&<section className="report-section"><div className="section-kicker">06 · LIMITATIONS</div><h2>What this analysis cannot establish</h2><ul className="readable-list">{limits.slice(0,30).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></section>}
    {Array.isArray(q.checks)&&q.checks.length>0&&<section className="report-section"><div className="section-kicker">07 · VALIDATION RECORD</div><h2>Checks performed</h2><div className="detail-list">{q.checks.slice(0,50).map((x:any,i:number)=><div className="detail-row" key={x.check_id||i}><span>{pretty(String(x.status||"not reported"))}</span><strong>{displayValue(x.message||x.check_id||x)}</strong></div>)}</div></section>}
    <p className="report-disclaimer">Decision support only. Verify operational findings against plant telemetry, inverter records and qualified site personnel.</p>
  </div>;
}

function ValidationLab({result,datasetName}:{result:ApiResult;datasetName:string}) {
  const ml=result.ml_analysis||{},q=ml.data_quality||{};
  const checks:any[]=Array.isArray(q.checks)?q.checks:[];
  const anomalies=Array.isArray(ml.anomalies)?ml.anomalies:[];
  const hypotheses=Array.isArray(ml.hypotheses)?ml.hypotheses:[];
  const evidence=Array.isArray(ml.evidence)?ml.evidence:[];
  const limits=Array.isArray(ml.limitations)?ml.limitations:[];
  const pass=checks.filter(x=>["pass","passed","success"].includes(String(x.status||"").toLowerCase())).length;
  const warn=checks.filter(x=>String(x.status||"").toLowerCase()==="warning").length;
  const fail=checks.filter(x=>["fail","failed","error"].includes(String(x.status||"").toLowerCase())).length;
  const groups=anomalies.reduce((acc:Record<string,number>,x:any)=>{const key=String(x?.category||x?.type||x?.anomaly_type||"Other finding").replaceAll("_"," ");acc[key]=(acc[key]||0)+1;return acc;},{});
  return <div className="analysis-card validation-page"><div className="eyebrow">VALIDATION LAB · EVIDENCE REVIEW</div><h2>Why should you trust this result?</h2><p className="analysis-summary">Explore the data-quality checks, evidence and limitations returned by deterministic ML. This is a transparent review of the pipeline, not independent field verification.</p>
    <div className="validation-intro"><div><span className="section-kicker">ANALYSIS UNDER REVIEW</span><strong>{datasetName}</strong><small>Plant {result.plant_id||"not specified"} · {ml.interval?.row_count??q.rows??"Unknown"} rows inspected</small></div><span className={"status-chip "+(fail?"status-fail":warn?"status-warn":"status-pass")}>{fail?"Review required":warn?"Passed with warnings":"Checks reported"}</span></div>
    <div className="metric-grid validation-kpis">{[["Checks recorded",checks.length],["Passed",pass],["Warnings",warn],["Failures",fail]].map(([label,value])=><div className="metric-card" key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <section className="validation-panel"><div className="section-kicker">CHECK OUTCOMES</div><h3>Data-quality validation</h3><p>Number of checks returned for each outcome.</p><ValidationBars checks={checks}/></section>
    <section className="validation-panel"><div className="section-kicker">CHECK REGISTER</div><h3>What the pipeline checked</h3>{checks.length?<div className="validation-checks">{checks.map((x:any,i:number)=><article key={x.check_id||i}><span className={"check-mark "+String(x.status||"").toLowerCase()}>{["pass","passed","success"].includes(String(x.status||"").toLowerCase())?"✓":String(x.status||"").toLowerCase()==="warning"?"!":"•"}</span><div><strong>{pretty(String(x.check_id||"Validation check"))}</strong><p>{displayValue(x.message||x.description||"Recorded by the ML pipeline.")}</p></div><small>{pretty(String(x.status||"not reported"))}</small></article>)}</div>:<p>No individual checks were returned. Overall data-quality status: <b>{pretty(String(q.status||"not reported"))}</b>.</p>}</section>
    <section className="validation-panel"><div className="section-kicker">ANOMALY REVIEW</div><h3>Findings by category</h3>{Object.keys(groups).length?<div className="category-bars">{Object.entries(groups).map(([name,count])=><div className="category-row" key={name}><span>{pretty(name)}</span><div><i style={{width:Number(count)/Math.max(1,...Object.values(groups))*100+"%"}}/></div><b>{count}</b></div>)}</div>:<p>No anomaly categories were returned.</p>}{anomalies.length>0&&<ul className="readable-list">{anomalies.slice(0,30).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul>}</section>
    {hypotheses.length>0&&<section className="validation-panel"><h3>Possible contributing factors</h3><p className="report-note">Hypotheses are not confirmed faults.</p><ul className="readable-list">{hypotheses.slice(0,20).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></section>}
    {evidence.length>0&&<section className="validation-panel"><h3>Supporting observations</h3><ul className="readable-list">{evidence.slice(0,30).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></section>}
    {limits.length>0&&<section className="validation-panel"><h3>Limitations and uncertainty</h3><ul className="readable-list">{limits.slice(0,20).map((x:any,i:number)=><li key={i}>{displayValue(x)}</li>)}</ul></section>}
    <div className="validation-caution"><strong>Operational verification still matters.</strong><p>Compare timestamps and devices with inverter alarms, maintenance records and site logs. A model hypothesis is not proof of an equipment fault.</p></div>
  </div>;
}

function AnalysisResponse({result}:{result:ApiResult}) {
  const a=result.analysis;
  const mlStatus = result.ml_analysis?.analysis_status;
  const sections:Array<[string,string[]|undefined,string]>=[
    ["What the readings tell us",a.observations,"No observations were returned."],
    ["Possible explanations",a.possible_causes,"No supported causes were identified."],
    ["Evidence considered",a.supporting_evidence,"No specific supporting evidence was identified."],
    ["Recommended checks",a.recommended_checks,"No checks were returned."],
    ["Limitations and uncertainty",a.limitations,"No limitations were reported."]
  ];
  return <div className="assistant-response"><div className="assistant-answer-heading"><span className="assistant-mark">✳</span><div><strong>SolarSleuth analysis</strong><small>Evidence-grounded explanation · {pretty(a.confidence||"insufficient_evidence")} confidence</small></div></div>{mlStatus&&<div className="analysis-state-row"><span className={"status-chip "+(mlStatus==="partial"?"status-warn":mlStatus==="success"?"":"status-fail")}>ML analysis: {pretty(String(mlStatus))}</span>{(result.model==="unavailable"||result.model==="deterministic-fallback")&&<span className="ai-unavailable-note" role="status">{result.model==="deterministic-fallback"?"Local AI unavailable · answering from saved deterministic ML evidence":"AI explanation unavailable · deterministic ML findings are still available below"}</span>}</div>}<p className="analysis-summary">{a.summary||"The model did not return a summary."}</p><div className="answer-sections">{sections.map(([title,items,fallback],i)=><section className="answer-section" key={title}><h3><span>{["◉","⌁","↗","✓","ⓘ"][i]}</span>{title}</h3><ul>{listOrFallback(items,fallback).map((x,j)=><li key={j}>{displayValue(x)}</li>)}</ul></section>)}</div><p className="inline-note">AI-generated explanation · Verify hypotheses with plant telemetry and qualified operators.</p></div>;
}

function OverviewDashboard({history,plants,selectedPlantId,onPlantChange,onNavigate}:{history:Turn[];plants:Plant[];selectedPlantId:string;onPlantChange:(id:string)=>void;onNavigate:(page:"data"|"report"|"validation"|"assistant")=>void}) {
  const latest=history.filter(x=>x.result).slice(-1)[0],ml=latest?.result?.ml_analysis||{},e=ml.energy||{},q=ml.data_quality||{};
  const anomalies=Array.isArray(ml.anomalies)?ml.anomalies:[];
  const plant=plants.find(x=>x.plant_id===selectedPlantId);
  const metric=(v:unknown)=>typeof v==="number"&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:2})+" kWh":"Not reported";
  return <div className="overview-page"><div className="overview-welcome"><div><div className="eyebrow">SOLAR ASSET PERFORMANCE</div><h2>{plant?.name||"Plant overview"}</h2><p>{plant?.location||"Select a plant to review its latest performance."}</p></div><span className="ov-badge">{latest?"LATEST ANALYSIS":"AWAITING DATA"}</span></div>
    <div className="overview-toolbar"><label htmlFor="overviewPlant">Selected plant</label><select id="overviewPlant" value={selectedPlantId} onChange={e=>onPlantChange(e.target.value)}><option value="">Choose a registered plant</option>{plants.map(x=><option key={x.plant_id} value={x.plant_id}>{x.name}</option>)}</select><span>{history.length} saved report{history.length===1?"":"s"}</span></div>
    {!latest?<div className="analysis-card analysis-empty"><div className="empty-icon">☼</div><h3>No analysis for this plant yet</h3><p>Upload an operating dataset and select this plant to see its performance here.</p><button className="primary-action" onClick={()=>onNavigate("data")}>Upload plant data ↗</button></div>:<>
      <div className="overview-kpis">{[["Actual energy",metric(e.actual?.value_kwh??ml.actual_energy),"Measured by deterministic ML"],["Expected energy",metric(e.expected?.value_kwh??ml.expected_energy),"Reference from the analysis"],["Energy deviation",metric(e.deviation?.value_kwh??ml.deviation),"Returned by the ML service"],["Data quality",pretty(String(q.status||"not reported")),(q.rows??ml.interval?.row_count??"—")+" rows inspected"]].map(([label,value,note])=><article className="overview-kpi" key={String(label)}><small>{label}</small><strong>{value}</strong><span>{note}</span></article>)}</div>
      <div className="overview-columns"><section className="analysis-card overview-panel"><div className="section-kicker">ENERGY PERFORMANCE</div><h3>Expected versus actual</h3><EnergyPerformanceChart result={ml}/></section><section className="analysis-card overview-panel"><div className="section-kicker">PLANT SIGNALS</div><h3>What needs attention</h3><div className="signal-stat"><strong>{anomalies.length}</strong><span>anomaly records returned</span></div>{anomalies.slice(0,3).map((x:any,i:number)=><div className="signal-row" key={i}><span>{"0"+(i+1)}</span><p>{displayValue(x)}</p></div>)}{!anomalies.length&&<p className="report-note">No anomaly records were returned.</p>}</section></div>
      {Array.isArray(ml.device_performance)&&ml.device_performance.length>0&&<section className="analysis-card overview-panel device-panel"><div className="section-kicker">INVERTER-LEVEL PERFORMANCE</div><h3>Which inverters contributed to plant output?</h3><p className="report-note">Compare measured and expected energy across the detected devices.</p><DevicePerformance items={ml.device_performance}/></section>}
      <div className="overview-lower"><div><span className="section-kicker">LATEST DATASET</span><strong>{latest.question.replace("Dataset analysis: ","")}</strong><small>{new Date(latest.createdAt).toLocaleString()} · {ml.interval?.row_count??"—"} rows</small></div><div className="overview-actions"><button className="btn btn-ghost" onClick={()=>onNavigate("report")}>Open report</button><button className="btn btn-ghost" onClick={()=>onNavigate("validation")}>Review validation</button><button className="btn btn-primary" onClick={()=>onNavigate("assistant")}>Ask AI ↗</button></div></div>
    </>}
  </div>;
}


export default function App() {
  const [apiBase, setApiBase] = useState(getApiBase);
  const [theme, setTheme] = useState<"light"|"dark">("light");
  const [page, setPage] = useState<"overview"|"plants"|"data"|"validation"|"report"|"assistant">("overview");
  const [showAuth, setShowAuth] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [userName, setUserName] = useState("SolarSleuth user");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [authMode, setAuthMode] = useState<"signin"|"signup">("signin");
  const [fullName, setFullName] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [ready, setReady] = useState<"checking"|"ready"|"warming"|"offline">("checking");
  const [serviceChecks, setServiceChecks] = useState({ml:false,llm:false,model:false});
  const [turns, setTurns] = useState<Turn[]>([]);
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customApi, setCustomApi] = useState(getApiBase);
  const [plantId, setPlantId] = useState("");
  const [plants, setPlants] = useState<Plant[]>([]);
  const [dashboardPlantId, setDashboardPlantId] = useState("");
  const [plantHistory, setPlantHistory] = useState<Turn[]>([]);
  const [plantHistoryBusy, setPlantHistoryBusy] = useState(false);
  const [plantHistoryError, setPlantHistoryError] = useState("");
  const [compareLeftId, setCompareLeftId] = useState("");
  const [compareRightId, setCompareRightId] = useState("");
  const [plantName, setPlantName] = useState("");
  const [plantLocation, setPlantLocation] = useState("");
  const [plantCapacity, setPlantCapacity] = useState("");
  const [plantTimezone, setPlantTimezone] = useState("Asia/Kolkata");
  const [plantBusy, setPlantBusy] = useState(false);
  const [plantError, setPlantError] = useState("");
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [weatherFile, setWeatherFile] = useState<File | null>(null);
  const [forecastFile, setForecastFile] = useState<File | null>(null);
  const [devicesFile, setDevicesFile] = useState<File | null>(null);
  const [eventLogFile, setEventLogFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadStage, setUploadStage] = useState<"idle"|"running"|"complete"|"failed">("idle");
  const [uploadMode, setUploadMode] = useState("auto");
  const [uploadTimezone, setUploadTimezone] = useState("");
  const [uploadInterval, setUploadInterval] = useState("");
  const [uploadSheet, setUploadSheet] = useState("");

  useEffect(() => {
    try {
      const t=localStorage.getItem("solarsleuth_theme"); if(t==="light"||t==="dark")setTheme(t);
      const token=localStorage.getItem("solarsleuth_access_token");
      if(token){
        setAccessToken(token);
        fetch(getApiBase()+"/api/v1/auth/me",{headers:{Authorization:"Bearer "+token}})
          .then(async response=>{if(!response.ok)throw new Error("Session expired");return response.json();})
          .then(async user=>{setAuthed(true);setUserName(user.name);setEmail(user.email);setBusinessName(user.business_name||"");const history=await loadStoredAnalyses(getApiBase(),token);setTurns(history);setSelectedTurnId(history[history.length-1]?.id||"");try{await refreshPlants(getApiBase(),token)}catch{}})
          .catch(()=>{localStorage.removeItem("solarsleuth_access_token");setAccessToken("");});
      }
    } catch {}
  }, []);
  useEffect(() => { document.documentElement.dataset.theme=theme; try{localStorage.setItem("solarsleuth_theme",theme)}catch{} },[theme]);
  useEffect(() => {
    if (!authed || !accessToken || !dashboardPlantId) {
      setPlantHistory([]);
      return;
    }
    let active = true;
    setPlantHistoryBusy(true);
    setPlantHistoryError("");
    loadPlantHistory(apiBase, accessToken, dashboardPlantId)
      .then(items => {
        if (!active) return;
        setPlantHistory(items);
        setCompareLeftId(items[0]?.id || "");
        setCompareRightId(items[1]?.id || items[0]?.id || "");
      })
      .catch(err => {
        if (active) {
          setPlantHistory([]);
          setPlantHistoryError(err instanceof Error ? err.message : "Unable to load plant history.");
        }
      })
      .finally(() => { if (active) setPlantHistoryBusy(false); });
    return () => { active = false; };
  }, [apiBase, accessToken, authed, dashboardPlantId]);

  useEffect(() => {
    if (!accessToken || !selectedTurnId) { setChatMessages([]); return; }
    let active = true;
    fetch(apiBase + "/api/v1/analyses/" + encodeURIComponent(selectedTurnId) + "/chat", {
      headers: { Authorization: "Bearer " + accessToken }, signal: AbortSignal.timeout(15000)
    }).then(async response => {
      if (!response.ok) throw new Error("Conversation history is unavailable for this report.");
      return response.json();
    }).then(data => { if (active) setChatMessages(Array.isArray(data.messages) ? data.messages : []); })
      .catch(() => { if (active) setChatMessages([]); });
    return () => { active = false; };
  }, [apiBase, accessToken, selectedTurnId]);

  const checkReady = useCallback(async () => {
    try { const r=await fetch(apiBase+"/ready",{signal:AbortSignal.timeout(8000)}); const j=await r.json(); const checks={ml:Boolean(j.ml_service_reachable),llm:Boolean(j.llm_api_reachable),model:Boolean(j.model_loaded)}; setServiceChecks(checks); setReady(r.ok&&checks.ml&&checks.llm?(checks.model?"ready":"warming"):"offline"); }
    catch { setServiceChecks({ml:false,llm:false,model:false}); setReady("offline"); }
  },[apiBase]);
  useEffect(() => { void checkReady(); const id=window.setInterval(()=>void checkReady(),15000); return ()=>window.clearInterval(id); },[checkReady]);


  const refreshPlants = async (base = apiBase, token = accessToken) => {
    if (!token) return;
    const response = await fetch(base + "/api/v1/plants", {
      headers: { Authorization: "Bearer " + token }, signal: AbortSignal.timeout(15000)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to load plants.");
    const items: Plant[] = Array.isArray(data.items) ? data.items : [];
    setPlants(items);
    setPlantId(current => current || items[0]?.plant_id || "");
    setDashboardPlantId(current => current || items[0]?.plant_id || "");
  };
  const createPlant = async (e: FormEvent) => {
    e.preventDefault();
    const name = plantName.trim();
    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (name.length < 2 || !id) { setPlantError("Enter a valid plant name."); return; }
    setPlantBusy(true); setPlantError("");
    try {
      const response = await fetch(apiBase + "/api/v1/plants", {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + accessToken },
        body: JSON.stringify({ plant_id: id, name, location: plantLocation.trim() || null,
          capacity_kw: plantCapacity.trim() ? Number(plantCapacity) : null,
          timezone: plantTimezone.trim() || null }),
        signal: AbortSignal.timeout(15000)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to register this plant.");
      await refreshPlants();
      setPlantId(data.plant_id); setDashboardPlantId(data.plant_id); setPlantName(""); setPlantLocation(""); setPlantCapacity("");
    } catch (err) { setPlantError(err instanceof Error ? err.message : "Unable to register plant."); }
    finally { setPlantBusy(false); }
  };
  const startDemo = () => { if(authed){setShowAuth(false);setPage("overview")}else setShowAuth(true); };
  const login = async (e: FormEvent) => {
    e.preventDefault(); setAuthError("");
    const cleanEmail=email.trim().toLowerCase();
    if(!cleanEmail||!password){setAuthError("Enter your email and password.");return;}
    if(authMode==="signup"){
      if(fullName.trim().length<2){setAuthError("Enter your name (at least 2 characters).");return;}
      if(businessName.trim().length<2){setAuthError("Enter your business or organisation name.");return;}
      if(password.length<10||password.length>128){setAuthError("Use a password between 10 and 128 characters.");return;}
      if(password!==confirmPassword){setAuthError("The passwords do not match.");return;}
    }
    try{
      const response=await fetch(apiBase+(authMode==="signup"?"/api/v1/auth/register":"/api/v1/auth/login"),{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(authMode==="signup"
          ?{email:cleanEmail,password,name:fullName.trim(),business_name:businessName.trim()}
          :{email:cleanEmail,password}),
        signal:AbortSignal.timeout(15000)
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Account request failed (HTTP ${response.status}).`);
      if(!data.access_token||!data.user)throw new Error("The account service returned an invalid response.");
      localStorage.setItem("solarsleuth_access_token",data.access_token);
      setAccessToken(data.access_token);setUserName(data.user.name);setEmail(data.user.email);
      setBusinessName(data.user.business_name||"");const history=await loadStoredAnalyses(apiBase,data.access_token);setTurns(history);setSelectedTurnId(history[history.length-1]?.id||"");try{await refreshPlants(apiBase,data.access_token)}catch{}setAuthed(true);setShowAuth(false);setPage("overview");
      setPassword("");setConfirmPassword("");
    }catch(err){
      setAuthError(err instanceof Error?err.message:"Unable to reach the account service. Check the backend and MongoDB configuration.");
    }
  };
  const logout = () => {
    setAuthed(false);setAccessToken("");setPassword("");
    try{localStorage.removeItem("solarsleuth_access_token")}catch{}
    setPage("overview");
  };
  const uploadDataset = async (e: FormEvent) => {
    e.preventDefault();
    if(!datasetFile){setError("Choose a CSV or XLSX dataset first.");return;}
    const extension = datasetFile.name.split(".").pop()?.toLowerCase();
    if (!["csv", "xlsx"].includes(extension || "")) { setError("Only CSV and XLSX files are supported."); return; }
    const allFiles = [datasetFile, weatherFile, forecastFile, devicesFile, eventLogFile].filter((item): item is File => Boolean(item));
    if (allFiles.some(item => item.size === 0)) { setError("One of the selected files is empty."); return; }
    if (allFiles.some(item => !["csv", "xlsx"].includes(item.name.split(".").pop()?.toLowerCase() || ""))) { setError("All selected inputs must be CSV or XLSX files."); return; }
    if (allFiles.reduce((total, item) => total + item.size, 0) > 25 * 1024 * 1024) { setError("The combined upload exceeds the 25 MiB limit."); return; }
    if (datasetFile.size === 0) { setError("The selected file is empty."); return; }
    const form=new FormData();
    form.append("file",datasetFile);
    if(weatherFile)form.append("weather_file",weatherFile);
    if(forecastFile)form.append("forecast_file",forecastFile);
    if(devicesFile)form.append("devices_file",devicesFile);
    if(eventLogFile)form.append("event_log_file",eventLogFile);
    form.append("plant_id",plantId.trim()||"unknown-plant");
    form.append("mode",uploadMode);
    if(uploadTimezone.trim())form.append("timezone",uploadTimezone.trim());
    if(uploadInterval.trim())form.append("interval_minutes",uploadInterval.trim());
    if(uploadSheet.trim())form.append("sheet_name",uploadSheet.trim());
    const id=Date.now().toString(36)+Math.random().toString(36).slice(2,7);
    setError("");setBusy(true);setUploadStage("running");setPage("overview");
    setTurns(old=>[...old,{id,question:`Dataset analysis: ${datasetFile.name}`,createdAt:Date.now(),loading:true}]);
    try{
      const response=await fetch(apiBase+"/api/v1/analyze/upload",{method:"POST",headers:{Authorization:"Bearer "+accessToken},body:form,signal:AbortSignal.timeout(540000)});
      const raw=await response.json().catch(() => ({}));
      if(!response.ok)throw new Error(typeof raw.detail==="string"?raw.detail:raw.detail?.message || `Analysis request failed (HTTP ${response.status}).`);
      if(!raw.ml_analysis) throw new Error("The backend response did not include the deterministic ML result.");
      if(!raw.analysis || typeof raw.analysis !== "object") throw new Error("The backend response did not include a valid AI explanation.");
      setUploadStage("complete");
      const savedId=raw.request_id||id;
      setTurns(old=>old.map(t=>t.id===id?{...t,id:savedId,loading:false,result:raw}:t));
      setSelectedTurnId(savedId);setDashboardPlantId(plantId.trim()||dashboardPlantId);setPlantHistory(old=>[...old.filter(t=>t.id!==savedId),{id:savedId,question:"Dataset analysis: "+datasetFile.name,createdAt:Date.now(),result:raw}]);setPage("overview");
    }catch(err){
      const msg=err instanceof Error?err.message:"Unable to complete dataset analysis.";
      setUploadStage("failed");
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,error:msg}:t));setError(msg);
    }finally{setBusy(false);}
  };

  const sendFollowUp = async (e: FormEvent) => {
    e.preventDefault();
    const question = chatInput.trim();
    if (!latestTurn?.result?.request_id || !question || chatBusy) return;
    const requestId = latestTurn.result.request_id;
    setChatBusy(true); setChatError(""); setChatInput("");
    setChatMessages(old => [...old, { role: "user", content: question },
      { role: "assistant", content: "Preparing an evidence-grounded response…" }]);
    const updateStreamingAnswer = (content: string | Analysis, model?: string) => {
      setChatMessages(old => {
        const next = [...old];
        const last = next[next.length - 1];
        if (last?.role === "assistant") next[next.length - 1] = { ...last, content, ...(model ? { model } : {}) };
        return next;
      });
    };
    try {
      let response = await fetch(apiBase + "/api/v1/analyses/" + encodeURIComponent(requestId) + "/chat/stream", {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + accessToken },
        body: JSON.stringify({ question }), signal: AbortSignal.timeout(300000)
      });
      let usedFallback = false;
      // Older deployed backends may expose /chat but not /chat/stream yet.
      if (response.status === 404 || response.status === 405) {
        const fallback = await fetch(apiBase + "/api/v1/analyses/" + encodeURIComponent(requestId) + "/chat", {
          method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + accessToken },
          body: JSON.stringify({ question }), signal: AbortSignal.timeout(300000)
        });
        if (fallback.ok) {
          const data = await fallback.json();
          if (!data.answer) throw new Error("The chat service returned an empty answer.");
          updateStreamingAnswer(data.answer);
          usedFallback = true;
        } else {
          const data = await fallback.json().catch(() => ({}));
          const detail = typeof data.detail === "string" ? data.detail : "The saved analysis could not be found. Reopen the report and try again.";
          throw new Error(detail);
        }
      }
      if (!usedFallback) {
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          const detail = typeof data.detail === "string" ? data.detail : "The follow-up request could not be completed.";
          throw new Error(detail);
        }
        if (!response.body) throw new Error("This browser could not open the streaming response. Please retry.");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let streamed = "";
        let completed = false;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split(/\r?\n\r?\n/);
          buffer = events.pop() || "";
          for (const event of events) {
            const eventName = event.match(/^event:\s*(.+)$/m)?.[1]?.trim();
            const dataLine = event.split(/\r?\n/).find(line => line.startsWith("data:"));
            if (!dataLine) continue;
            const payload = JSON.parse(dataLine.slice(5).trim() || "{}");
            if (eventName === "delta" && typeof payload.text === "string") {
              streamed += payload.text;
              updateStreamingAnswer(streamed);
            } else if (eventName === "done" && payload.answer) {
              updateStreamingAnswer(payload.answer);
              completed = true;
            }
          }
        }
        if (!completed) throw new Error("The response stream ended before the answer was complete. Please retry.");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to send the follow-up question.";
      setChatError(message);
      updateStreamingAnswer("I couldn't complete that response. Your question is still in this thread; please retry.");
    } finally { setChatBusy(false); }
  };
  const statusText=ready==="ready"?"ML + local AI ready":ready==="warming"?"ML connected · local AI model warming up":ready==="checking"?"Checking backend, ML and AI services":"Backend or a dependent service unavailable";
  const nav=[{id:"overview" as const,label:"Overview",icon:"◫"},{id:"plants" as const,label:"Plants",icon:"⌂"},{id:"data" as const,label:"Upload & analyse",icon:"⇧"},{id:"validation" as const,label:"Validation Lab",icon:"✓"},{id:"report" as const,label:"Reports",icon:"▤"},{id:"assistant" as const,label:"AI Assistant",icon:"✳"}];
  const plantScopedTurns = turns.filter(t=>t.result && (!dashboardPlantId || t.result.plant_id===dashboardPlantId));
  const latestTurn = plantScopedTurns.find(t=>t.id===selectedTurnId) || plantScopedTurns.slice(-1)[0];
  const compareLeft = plantHistory.find(t => t.id === compareLeftId);
  const compareRight = plantHistory.find(t => t.id === compareRightId);
  const comparisonMetrics = [{ key: "forecast", label: "Forecast energy" }, { key: "expected", label: "Expected energy" }, { key: "actual", label: "Actual energy" }, { key: "deviation", label: "Deviation" }];

  return <>
    {showAuth&&<div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="authTitle" onClick={e=>{if(e.target===e.currentTarget)setShowAuth(false)}}><div className="auth-card"><button className="modal-close" aria-label="Close sign-in" onClick={()=>setShowAuth(false)}>×</button><div className="auth-brand"><BrandMark/><b>SolarSleuth</b></div><div className="eyebrow">DEMO WORKSPACE ACCESS</div><h2 id="authTitle">Your solar intelligence workspace.</h2><div className="auth-tabs"><button type="button" className={authMode==="signin"?"on":""} onClick={()=>{setAuthMode("signin");setAuthError("")}}>Sign in</button><button type="button" className={authMode==="signup"?"on":""} onClick={()=>{setAuthMode("signup");setAuthError("")}}>Create account</button></div><form onSubmit={login}>{authMode==="signup"&&<><label htmlFor="authName">Your name</label><input id="authName" autoComplete="name" value={fullName} onChange={e=>setFullName(e.target.value)} placeholder="e.g. Alex Morgan"/><label htmlFor="businessName">Business / organisation</label><input id="businessName" autoComplete="organization" value={businessName} onChange={e=>setBusinessName(e.target.value)} placeholder="Your company or plant operator name"/></>}<label htmlFor="authEmail">Email address</label><input id="authEmail" type="email" autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/><label htmlFor="authPassword">Password</label><input id="authPassword" type="password" autoComplete={authMode==="signup"?"new-password":"current-password"} value={password} onChange={e=>setPassword(e.target.value)} placeholder={authMode==="signup"?"At least 10 characters":"Enter your password"}/>{authMode==="signup"&&<><label htmlFor="authConfirm">Confirm password</label><input id="authConfirm" type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} placeholder="Repeat password"/></>}{authError&&<div className="auth-error" role="alert">{authError}</div>}<button className="btn btn-primary btn-lg btn-full" type="submit">{authMode==="signup"?"Create demo account ↗":"Enter demo workspace ↗"}</button></form><p className="inline-note">Accounts are stored by the backend in MongoDB. Passwords are securely hashed; each account receives a separate business workspace.</p></div></div>}
    {!authed ? <section id="landing" className="landing-shell">
      <header className="topbar landing-topbar"><a className="brand" href="#home"><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><button className="signin-btn" onClick={()=>setShowAuth(true)}>Sign in</button></div></header>
      <div className="hero-grid"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line"></span> SOLAR ASSET INTELLIGENCE · GLOBATHON 2026</div><h1>When output falls short,<br/>find the <span>reason behind it.</span></h1><p className="hero-lede">Turn solar plant readings into an evidence-aware explanation. Explore performance, review possible causes and keep uncertainty visible — with a local AI model running on your machine.</p><div className="hero-actions"><button className="btn btn-primary btn-lg" id="startdemo" onClick={startDemo}>Explore the live demo <span aria-hidden="true"> ↗ </span></button><a className="text-link" href="#how">See how it works <span> ↓ </span></a></div><div className="hero-proof"><div className="proof-avatars"><span>PV</span><span>AI</span><span>✓</span></div><div><b>Explainable by design</b><small>Local inference · Evidence-first explanations · Human verification</small></div></div></div><div className="hero-visual" aria-label="Illustrative solar performance visualization"><div className="visual-orbit orbit-one"></div><div className="visual-orbit orbit-two"></div><div className="sun-glow"></div><div className="solar-art"><div className="sun-disc"></div><div className="sun-ray ray-a"></div><div className="sun-ray ray-b"></div><div className="sun-ray ray-c"></div><div className="solar-hill hill-back"></div><div className="solar-hill hill-front"></div><div className="panel-grid">{Array.from({length:12},(_,i)=><span key={i}/>)}</div></div><div className="visual-caption">LOCAL AI · SOLAR PERFORMANCE INTELLIGENCE</div></div></div>
      <div className="trust-strip"><div><b>Local</b><span>on-device model inference</span></div><div><b>Evidence</b><span>structured observations</span></div><div><b>Human</b><span>verification stays essential</span></div><div><b>Private</b><span>no cloud AI dependency</span></div></div>
      <section className="landing-section" id="how"><div className="section-heading"><div><div className="eyebrow">FROM READINGS TO EVIDENCE</div><h2>A clearer view of every solar performance gap.</h2></div><p>Built for operators and analysts who need a useful explanation without confusing a model hypothesis with a confirmed fault.</p></div><div className="feature-grid"><article className="feature-card"><span className="feature-number">01 / OBSERVE</span><div className="feature-icon icon-sun">☼</div><h3>Bring the readings together</h3><p>Upload a CSV or Excel workbook; the ML pipeline validates and maps the available measurements.</p></article><article className="feature-card"><span className="feature-number">02 / EXPLAIN</span><div className="feature-icon icon-unknown">◌</div><h3>Keep uncertainty visible</h3><p>Separate observations from possible causes, checks and limitations in the model's response.</p></article><article className="feature-card"><span className="feature-number">03 / VERIFY</span><div className="feature-icon icon-validate">✓</div><h3>Act on evidence, not guesses</h3><p>Use recommendations as verification steps, not proof that a fault has occurred.</p></article></div></section>
      <footer className="site-footer"><span>SolarSleuth © 2026</span><span>Globathon · Solar Recovery Intelligence</span><span>Local prototype · Demo authentication</span></footer>
    </section> : <>
      <header className="topbar"><a className="brand" href="#home" onClick={e=>{e.preventDefault();setPage("overview")}}><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className="status-dot"></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><div className="avatar-wrap"><button className="avatar-btn" title="Account menu" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)}>{userName.charAt(0)}</button><div className={"user-menu "+(menuOpen?"":"hide")}><div className="um-name">{userName}</div><div className="um-email">{businessName||email}</div><button className="um-out" onClick={()=>{setMenuOpen(false);logout()}}>Sign out</button></div></div></div></header>
      <div className="app-shell"><aside className="sidebar"><div className="sidebar-label">WORKSPACE</div><nav className="side-nav">{nav.map(n=><button key={n.id} className={page===n.id?"on":""} onClick={()=>setPage(n.id)}><span>{n.icon}</span>{n.label}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-mini-icon">✳</div><div><b>{userName}</b><small>{businessName||email}</small></div><span className="live-dot"></span></div></aside>
      <main className="workspace"><div className="workspace-head"><div><div className="breadcrumb">WORKSPACE <span>/</span> <b>{nav.find(n=>n.id===page)?.label}</b></div><h1>{page==="overview"?"Plant overview":page==="data"?"Upload & analyse":page==="validation"?"Validation Lab":page==="report"?"Reports":page==="plants"?"Plants & performance":"AI Assistant"}</h1><p>{page==="overview"?"A file-driven view of your latest analysis and local service readiness.":page==="data"?"Upload a CSV or Excel workbook for validation, deterministic analysis, and AI explanation.":page==="validation"?"Inspect data-quality checks, ML evidence and findings that need operational verification.":page==="report"?"Review and print the latest dataset-derived report.":page==="plants"?"Manage plants, inspect their saved analysis history and compare ML reports.":"Chat with the local AI about the selected plant and its saved analysis."}</p></div><div className="head-actions"><span className="plant-select-label">LATEST UPLOAD</span><div className="plant-select"><span className="plant-icon">☼</span><span><b>{turns.filter(t=>t.result).slice(-1)[0]?.question.replace("Dataset analysis: ","") || "No dataset analysed"}</b><small>{turns.filter(t=>t.result).length} successful analysis result(s)</small></span></div></div></div>
      <section className="controls-panel"><div><label>Service status</label><div className="engine-status"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</div><small className="service-breakdown">ML API: {serviceChecks.ml?"reachable":"unavailable"} · LLM API: {serviceChecks.llm?"reachable":"unavailable"} · Model: {serviceChecks.model?"loaded":"not loaded"}</small></div><div><label>Backend API</label><input aria-label="Backend API URL" value={customApi} onChange={e=>setCustomApi(e.target.value)} style={{maxWidth:280}}/></div><button className="small-action" onClick={()=>{const b=customApi.trim().replace(/\/$/,"");if(b){setApiBase(b);try{localStorage.setItem("solarsleuth_api_base",b)}catch{}setReady("checking");setTimeout(()=>void checkReady(),50)}}}>Connect</button></section>
      {page==="overview"&&<>{busy&&<p className="pipeline-status" role="status"><span className="inline-spinner" aria-hidden="true"/> Analysing the selected plant data. The deterministic ML pipeline and local explanation service are working.</p>}{error&&<div className="inline-error" role="alert">{error}</div>}<OverviewDashboard history={dashboardPlantId?plantHistory:[]} plants={plants} selectedPlantId={dashboardPlantId} onPlantChange={(id)=>{setDashboardPlantId(id);const matches=turns.filter(t=>t.result&&t.result.plant_id===id);setSelectedTurnId(matches[matches.length-1]?.id||"");}} onNavigate={setPage}/></>} 
      {page==="plants"&&<div className="analysis-card"><div className="eyebrow">ASSET MANAGEMENT · WORKSPACE</div><h2>Plant directory & performance</h2><p className="analysis-summary">Manage registered plants, inspect each plant's saved analysis history and compare two reports using only metrics returned by deterministic ML.</p>
        {plants.length > 0 && <section className="dataset-profile" style={{marginBottom:22}}>
          <div className="dataset-profile-head"><h4>Plant performance dashboard</h4><span>Business workspace · plant-scoped history</span></div>
          <div className="field-card"><label htmlFor="dashboardPlant">Select plant</label><select id="dashboardPlant" value={dashboardPlantId} onChange={e=>setDashboardPlantId(e.target.value)}>{plants.map(plant=><option key={plant.plant_id} value={plant.plant_id}>{plant.name} · {plant.plant_id}</option>)}</select></div>
          {plantHistoryBusy ? <p className="inline-note">Loading saved reports for this plant…</p> : plantHistoryError ? <div className="inline-error" role="alert">{plantHistoryError}</div> : <><div className="metric-grid">
            <div className="metric-card"><span>Saved reports loaded</span><strong>{plantHistory.length}</strong></div>
            <div className="metric-card"><span>Latest ML status</span><strong>{plantHistory[plantHistory.length-1]?.result?.ml_analysis?.analysis_status || "No report"}</strong></div>
            <div className="metric-card"><span>Latest analysis</span><strong>{plantHistory.length ? new Date(plantHistory[plantHistory.length-1].createdAt).toLocaleDateString() : "No report"}</strong></div>
          </div>
          <h4 style={{marginTop:20}}>Analysis history</h4>
          {plantHistory.length===0 ? <p>No saved analyses exist for this plant yet. Upload a dataset and select this plant.</p> : <div className="dataset-facts">{plantHistory.slice().reverse().map(item=><div key={item.id}><small>{new Date(item.createdAt).toLocaleString()}</small><strong>{item.question.replace("Dataset analysis: ","")}</strong><span>ML status: {item.result?.ml_analysis?.analysis_status || "Not reported"}</span><button type="button" className="small-action" onClick={()=>{setTurns(old=>old.some(t=>t.id===item.id)?old:old.concat(item));setSelectedTurnId(item.id);setPage("report")}}>Open report ↗</button></div>)}</div>}
          {plantHistory.length>=2 && <><h4 style={{marginTop:22}}>Compare two reports</h4><div className="field-grid">
            <div className="field-card"><label htmlFor="compareLeft">Earlier / baseline report</label><select id="compareLeft" value={compareLeftId} onChange={e=>setCompareLeftId(e.target.value)}>{plantHistory.map(item=><option key={item.id} value={item.id}>{new Date(item.createdAt).toLocaleDateString()} · {item.question.replace("Dataset analysis: ","")}</option>)}</select></div>
            <div className="field-card"><label htmlFor="compareRight">Report to compare</label><select id="compareRight" value={compareRightId} onChange={e=>setCompareRightId(e.target.value)}>{plantHistory.map(item=><option key={item.id} value={item.id}>{new Date(item.createdAt).toLocaleDateString()} · {item.question.replace("Dataset analysis: ","")}</option>)}</select></div>
          </div>
          {compareLeft && compareRight && <div style={{overflowX:"auto",marginTop:14}}><table className="comparison-table"><thead><tr><th>ML metric</th><th>Baseline</th><th>Comparison</th><th>Change (comparison − baseline)</th></tr></thead><tbody>{comparisonMetrics.map(metric=>{const a=energyMetric(compareLeft,metric.key);const b=energyMetric(compareRight,metric.key);const delta=a!==null&&b!==null?b-a:null;return <tr key={metric.key}><td>{metric.label}</td><td>{formatEnergy(a)}</td><td>{formatEnergy(b)}</td><td>{delta===null?"Not comparable":(delta>0?"+":"")+formatEnergy(delta)}</td></tr>;})}</tbody></table><p className="inline-note">Values are read directly from each saved ML result. Missing metrics remain unavailable; no values are estimated or recalculated.</p></div>}
          </>}
          </>}
        </section>}

        {plantError&&<div className="inline-error" role="alert">{plantError}</div>}
        <div className="dataset-profile" style={{marginBottom:18}}><div className="dataset-profile-head"><h4>Registered plants</h4><span>{plants.length} plants</span></div>
          {plants.length===0?<p>No plants registered yet. Add your first plant below.</p>:<div className="dataset-facts">{plants.map(plant=><div key={plant.plant_id}><small>{plant.plant_id}</small><strong>{plant.name}</strong><span>{plant.location||"Location not set"}{plant.capacity_kw?" · "+plant.capacity_kw.toLocaleString()+" kW":""}</span><button type="button" className="small-action" onClick={()=>{setPlantId(plant.plant_id);setPage("data")}}>Use for upload ↗</button></div>)}</div>}
        </div>
        <form className="field-grid" onSubmit={createPlant}><div className="field-card"><label htmlFor="plantName">Plant name</label><input id="plantName" value={plantName} onChange={e=>setPlantName(e.target.value)} maxLength={120} placeholder="e.g. West Solar Farm" required/></div><div className="field-card"><label htmlFor="plantLocation">Location (optional)</label><input id="plantLocation" value={plantLocation} onChange={e=>setPlantLocation(e.target.value)} maxLength={200} placeholder="City / site"/></div><div className="field-card"><label htmlFor="plantCapacity">Installed capacity in kW (optional)</label><input id="plantCapacity" type="number" min="0.01" max="1000000" step="any" value={plantCapacity} onChange={e=>setPlantCapacity(e.target.value)} placeholder="e.g. 250"/></div><div className="field-card"><label htmlFor="plantTimezone">Plant timezone</label><input id="plantTimezone" value={plantTimezone} onChange={e=>setPlantTimezone(e.target.value)} maxLength={64} placeholder="Asia/Kolkata"/></div><div style={{gridColumn:"1 / -1"}}><button className="primary-action" type="submit" disabled={plantBusy||!plantName.trim()}>{plantBusy?"Saving plant…":"Register plant ↗"}</button></div></form>
      </div>}
      {page==="data"&&<div className="analysis-card"><div className="eyebrow">DATA INGESTION · CSV / XLSX</div><h2>Upload plant operating data</h2><p className="analysis-summary">The backend sends the file to the deterministic ML service first. Only its structured analysis is passed to the local LLM for explanation.</p><form onSubmit={uploadDataset} className="field-grid"><div className={"field-card upload-dropzone "+(dragActive?"drag-active":"")} style={{gridColumn:"1 / -1"}} onDragOver={e=>{e.preventDefault();setDragActive(true)}} onDragLeave={e=>{e.preventDefault();setDragActive(false)}} onDrop={e=>{e.preventDefault();setDragActive(false);const file=e.dataTransfer.files?.[0];if(file){setDatasetFile(file);setError("");setUploadStage("idle");}}}><label htmlFor="datasetFile">Operating data file</label><input id="datasetFile" type="file" accept=".csv,.xlsx" onChange={e=>{setDatasetFile(e.target.files?.[0]||null);setError("");setUploadStage("idle");}} required/><small>Drop a CSV or XLSX here, or choose a file · Maximum 25 MiB · Optional weather, forecast, device and event-log files supported</small>{datasetFile&&<div className="selected-file"><strong>{datasetFile.name}</strong><span>{(datasetFile.size/1024/1024).toFixed(2)} MiB</span><button type="button" className="small-action" onClick={()=>{setDatasetFile(null);setUploadStage("idle");}}>Remove</button></div>}</div>
<div className="field-card"><label htmlFor="weatherFile">Weather data (optional)</label><input id="weatherFile" type="file" accept=".csv,.xlsx" onChange={e=>setWeatherFile(e.target.files?.[0]||null)}/><small>{weatherFile?.name || "Hourly weather or irradiance readings"}</small></div><div className="field-card"><label htmlFor="forecastFile">Design forecast (optional)</label><input id="forecastFile" type="file" accept=".csv,.xlsx" onChange={e=>setForecastFile(e.target.files?.[0]||null)}/><small>{forecastFile?.name || "Needed for the forecast-vs-actual waterfall; include timestamp and forecast energy or AC power."}</small></div><div className="field-card"><label htmlFor="devicesFile">Device details (optional)</label><input id="devicesFile" type="file" accept=".csv,.xlsx" onChange={e=>setDevicesFile(e.target.files?.[0]||null)}/><small>{devicesFile?.name || "Inverter and plant specifications"}</small></div><div className="field-card"><label htmlFor="eventLogFile">Operator event log (optional)</label><input id="eventLogFile" type="file" accept=".csv,.xlsx" onChange={e=>setEventLogFile(e.target.files?.[0]||null)}/><small>{eventLogFile?.name || "Outages, curtailment and maintenance events"}</small></div><div className="field-card"><label htmlFor="plantId">Registered plant</label>{plants.length>0?<select id="plantId" value={plantId} onChange={e=>{setPlantId(e.target.value);const selected=plants.find(p=>p.plant_id===e.target.value);if(selected?.timezone)setUploadTimezone(selected.timezone)}}>{plants.map(plant=><option key={plant.plant_id} value={plant.plant_id}>{plant.name} · {plant.plant_id}</option>)}</select>:<><input id="plantId" value={plantId} maxLength={128} onChange={e=>setPlantId(e.target.value)} placeholder="Enter a plant identifier"/><small>No registered plants yet. Add one in Plant directory, or enter an identifier for legacy reports.</small></>}<small>Plant metadata is associated with this report; measurements always come from the uploaded file.</small></div><div className="field-card"><label htmlFor="uploadMode">Analysis mode</label><select id="uploadMode" value={uploadMode} onChange={e=>setUploadMode(e.target.value)}><option value="auto">Automatic</option><option value="snapshot">Snapshot</option><option value="full">Full time-series</option></select></div><div className="field-card"><label htmlFor="uploadTimezone">IANA timezone (optional)</label><input id="uploadTimezone" value={uploadTimezone} onChange={e=>setUploadTimezone(e.target.value)} placeholder="Asia/Kolkata"/></div><div className="field-card"><label htmlFor="uploadInterval">Interval minutes (optional)</label><input id="uploadInterval" type="number" min="0.01" step="any" value={uploadInterval} onChange={e=>setUploadInterval(e.target.value)} placeholder="Auto-detect"/></div><div className="field-card"><label htmlFor="uploadSheet">Excel sheet name (optional)</label><input id="uploadSheet" value={uploadSheet} onChange={e=>setUploadSheet(e.target.value)} placeholder="First sheet by default"/></div><div style={{gridColumn:"1 / -1"}}><button className="primary-action" type="submit" disabled={busy||!datasetFile}>{busy?<><span className="inline-spinner" aria-hidden="true"/> Analysing dataset…</>:"Upload and analyse ↗"}</button>{error&&<div className="inline-error" role="alert">{error}</div>}{uploadStage==="running"&&<p className="pipeline-status" role="status">Your file has been sent to the backend. Validation, deterministic ML analysis and local AI explanation are running in sequence.</p>}{uploadStage==="complete"&&<p className="pipeline-status success" role="status">Analysis completed. Review the ML evidence and AI explanation.</p>}{uploadStage==="failed"&&<p className="pipeline-status failed" role="status">The analysis could not be completed. Review the error above and retry when the services are ready.</p>}</div></form><p className="inline-note" style={{marginTop:14}}>The current HTTP integration accepts one operating-data file. The ML Python pipeline supports additional context inputs, but multi-file weather/device/forecast/event-log upload is not yet exposed here.</p><p className="inline-note">SolarSleuth is file-first: plant readings are never entered manually in the application.</p></div>}
      {page==="validation"&&(latestTurn?.result?.ml_analysis ? <ValidationLab result={latestTurn.result} datasetName={latestTurn.question.replace("Dataset analysis: ","")}/> : <div className="analysis-card analysis-empty"><div className="empty-icon">✓</div><h3>No analysis to validate yet</h3><p>Upload a CSV or Excel workbook first. The Validation Lab will show the data-quality checks and evidence returned by the deterministic ML service.</p><button className="primary-action" onClick={()=>setPage("data")}>Upload plant data ↗</button></div>)}

      {page==="report"&&<div className="analysis-card report report-shell"><div className="report-toolbar noprint"><div><div className="eyebrow">ANALYST REPORT</div><h2>Plant performance report</h2><p>Select a saved analysis to inspect the full evidence trail.</p></div><button className="primary-action" type="button" onClick={()=>window.print()} disabled={!latestTurn?.result}>Export PDF ↓</button></div><p className="report-export-hint noprint">Your browser will open the print dialog. Choose “Save as PDF” to download the report.</p>
        <div className="report-picker noprint">{turns.filter(t=>t.result&&(!dashboardPlantId||t.result.plant_id===dashboardPlantId)).map(t=><button key={t.id} type="button" className={t.id===latestTurn?.id?"selected":""} onClick={()=>setSelectedTurnId(t.id)}>{t.question.replace("Dataset analysis: ","")}<small>{new Date(t.createdAt).toLocaleDateString()}</small></button>)}</div>
        {latestTurn?.result?<div className="report-content"><header className="report-cover"><div className="eyebrow">SOLARSLEUTH · SOLAR PERFORMANCE INTELLIGENCE</div><h1>Plant performance analysis</h1><p>{latestTurn.question.replace("Dataset analysis: ","")}</p><div className="report-cover-meta"><span>Plant · {latestTurn.result.plant_id||"Not specified"}</span><span>Generated · {new Date(latestTurn.createdAt).toLocaleString()}</span><span>Analysis mode · {latestTurn.result.analysis_mode||"Automatic"}</span></div></header><MlAnalysisResponse result={latestTurn.result.ml_analysis||{}}/><section className="report-section"><div className="section-kicker">08 · AI EXPLANATION</div><h2>Analyst interpretation</h2><AnalysisResponse result={latestTurn.result}/></section></div>:<div className="analysis-empty"><p>No successful analysis is available yet.</p><button className="primary-action" onClick={()=>setPage("data")}>Run an analysis ↗</button></div>}
      </div>}

      {page==="assistant"&&<div className="chat-workspace">
        <header className="chat-workspace-head"><div><div className="eyebrow">PLANT-SCOPED AI ASSISTANT</div><h2>Ask SolarSleuth</h2><p>Answers are grounded in the selected plant's saved analysis. Measurements are never invented or recalculated.</p></div><div className="chat-context"><label htmlFor="chatReport">Analysis context</label><select id="chatReport" value={latestTurn?.id||""} onChange={e=>setSelectedTurnId(e.target.value)}><option value="">Select a saved analysis</option>{turns.filter(t=>t.result&&(!dashboardPlantId||t.result.plant_id===dashboardPlantId)).map(t=><option key={t.id} value={t.id}>{t.question.replace("Dataset analysis: ","")} · {new Date(t.createdAt).toLocaleDateString()}</option>)}</select></div></header>
        {!latestTurn?.result?<div className="chat-empty"><span className="chat-empty-mark">✳</span><h3>Choose an analysis to start</h3><p>Select a plant and one of its saved reports. Your conversation stays tied to that evidence.</p></div>:<>
          <div className="chat-context-note"><span className="live-dot"/> In context: <strong>{plants.find(p=>p.plant_id===latestTurn.result?.plant_id)?.name||latestTurn.result.plant_id||"Selected plant"}</strong><span>·</span>{latestTurn.question.replace("Dataset analysis: ","")}</div>
          <div className="chat-thread" aria-live="polite">
            {chatMessages.length===0&&<div className="chat-welcome"><span className="assistant-mark">✳</span><div><strong>SolarSleuth</strong><p>I've got the selected plant analysis in context. Ask me to explain a deviation, trace evidence behind a finding, or suggest what to verify next.</p><div className="chat-prompts">{["What is driving the energy deviation?","Which findings have the strongest evidence?","What should the site operator check first?"].map(question=><button key={question} type="button" onClick={()=>setChatInput(question)}>{question}<span>↗</span></button>)}</div></div></div>}
            {chatMessages.map((message,index)=><article className={"chat-turn "+message.role} key={message.created_at||index}>{message.role==="assistant"&&<span className="assistant-mark">✳</span>}<div className="chat-bubble">{message.role==="user"?<p>{typeof message.content==="string"?message.content:displayValue(message.content)}</p>:typeof message.content==="string"?<div className="chat-answer-text">{renderSafeMarkdown(message.content)}</div>:<AnalysisResponse result={{analysis:message.content as Analysis,plant_id:latestTurn.result?.plant_id,model:message.model}}/>}</div></article>)}
            {chatBusy&&<article className="chat-turn assistant"><span className="assistant-mark">✳</span><div className="typing-bubble"><i/><i/><i/><span>Reviewing plant evidence</span></div></article>}
          </div>
          <form className="chat-composer" onSubmit={sendFollowUp}><textarea aria-label="Ask a question about this plant" rows={1} maxLength={2000} value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();void sendFollowUp(e as any)}}} placeholder="Ask anything about this plant's analysis…" disabled={chatBusy}/><button type="submit" aria-label="Send message" disabled={chatBusy||!chatInput.trim()}>↑</button><small>Enter to send · Shift + Enter for a new line</small></form>
          {chatError&&<div className="inline-error" role="alert">{chatError}</div>}
        </>}
      </div>}
      </main></div><footer className="app-footer">SolarSleuth is a prototype. Confirm model hypotheses against real telemetry and qualified operator checks. Account access uses expiring backend-issued tokens.</footer>
    </>}
  </>;
}
