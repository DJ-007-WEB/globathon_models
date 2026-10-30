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
async function loadStoredAnalyses(base: string, token: string): Promise<Turn[]> {
  const headers = { Authorization: "Bearer " + token };
  const response = await fetch(base + "/api/v1/analyses?limit=100&offset=0", { headers, signal: AbortSignal.timeout(20000) });
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

function BrandMark() {
  return <span className="brand-mark"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 4 5 12.5v15L20 36l15-8.5v-15L20 4Z" fill="none" stroke="currentColor" strokeWidth="1.7"/><path d="M20 10v20M10 15.5l20 9M10 24.5l20-9" stroke="currentColor" strokeWidth="1.5"/><circle cx="20" cy="20" r="4" fill="currentColor"/></svg></span>;
}

function MlAnalysisResponse({ result }: { result: MlAnalysis }) {
  const energy = result.energy || {};
  const waterfall = result.waterfall || {};
  const fmt = (v: unknown, unit = "kWh") => typeof v === "number" && Number.isFinite(v) ? `${v.toLocaleString(undefined,{maximumFractionDigits:2})} ${unit}` : "Unavailable";
  const anomalies = Array.isArray(result.anomalies) ? result.anomalies : [];
  const hypotheses = Array.isArray(result.hypotheses) ? result.hypotheses : [];
  const limitations = Array.isArray(result.limitations) ? result.limitations : [];
  return <section className="analysis-section" style={{marginBottom:18}}>
    <div className="eyebrow">DETERMINISTIC ML · {String(result.analysis_status||"unknown").toUpperCase()}</div>
    <h3>Calculated plant analysis</h3>
    <p>{result.summary || "The ML service returned a structured analysis."}</p>
    <div className="dataset-profile">
      <div className="dataset-profile-head"><h4>Dataset profile</h4><span>{result.schema_version ? `Contract v${result.schema_version}` : "ML metadata"}</span></div>
      <div className="dataset-facts">
        <div><small>Rows analysed</small><strong>{result.interval?.row_count ?? result.data_quality?.rows ?? "Not reported"}</strong></div>
        <div><small>Sampling interval</small><strong>{typeof result.interval?.sampling_interval_seconds === "number" ? `${result.interval.sampling_interval_seconds} sec` : "Not reported"}</strong></div>
        <div><small>Timezone</small><strong>{result.interval?.timezone || result.request?.timezone || "Not resolved"}</strong></div>
        <div><small>Devices</small><strong>{result.interval?.device_count ?? "Not reported"}</strong></div>
      </div>
      {(result.interval?.start_utc || result.interval?.end_utc) && <p className="inline-note">Coverage: {result.interval?.start_utc || "Start unavailable"} — {result.interval?.end_utc || "End unavailable"}</p>}
      {result.units && <div className="unit-list"><strong>Units reported by ML</strong>{Object.entries(result.units).map(([key,value])=><span key={key}><small>{pretty(key)}</small><b>{String(value)}</b></span>)}</div>}
      {(result.mapping_version || result.vocab_version) && <p className="inline-note">Schema mapping version: {result.mapping_version || "Not reported"} · Vocabulary version: {result.vocab_version || "Not reported"}</p>}
      {Array.isArray(result.request?.source_files) && result.request.source_files.length>0 && <p className="inline-note">Source files: {result.request.source_files.map((name:string)=>String(name)).join(", ")}</p>}
    </div>
    <div className="metric-grid">
      <div className="metric-card"><span>Forecast energy</span><strong>{fmt(energy.forecast?.value_kwh ?? result.forecast_energy)}</strong></div>
      <div className="metric-card"><span>Expected energy</span><strong>{fmt(energy.expected?.value_kwh ?? result.expected_energy)}</strong></div>
      <div className="metric-card"><span>Actual energy</span><strong>{fmt(energy.actual?.value_kwh ?? result.actual_energy)}</strong></div>
      <div className="metric-card"><span>Deviation</span><strong>{fmt(energy.deviation?.value_kwh ?? result.deviation)}</strong></div>
    </div>
    {Object.keys(waterfall).length>0&&<div className="analysis-section"><h3>Energy waterfall</h3><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(waterfall,null,2)}</pre></div>}
    {anomalies.length>0&&<div className="analysis-section"><h3>Detected anomalies ({anomalies.length})</h3><ul>{anomalies.slice(0,20).map((a:any,i:number)=><li key={i}>{typeof a==="string"?a:JSON.stringify(a)}</li>)}</ul></div>}
    {hypotheses.length>0&&<div className="analysis-section"><h3>ML hypotheses</h3><ul>{hypotheses.slice(0,20).map((h:any,i:number)=><li key={i}>{typeof h==="string"?h:JSON.stringify(h)}</li>)}</ul></div>}
    {Array.isArray(result.evidence)&&result.evidence.length>0&&<div className="analysis-section"><h3>Deterministic ML evidence</h3><ul>{result.evidence.slice(0,30).map((x:any,i:number)=><li key={i}>{String(x)}</li>)}</ul></div>}
    {result.data_quality&&<div className="analysis-section"><h3>Data quality · {String(result.data_quality.status||"not reported")}</h3><p>{result.data_quality.rows??"—"} rows inspected · {result.data_quality.counts?.warning??0} warnings · {result.data_quality.counts?.fail??0} failures</p></div>}
    {Array.isArray(result.unresolved_fields)&&result.unresolved_fields.length>0&&<div className="analysis-section"><h3>Unresolved fields</h3><ul>{result.unresolved_fields.slice(0,30).map((x:any,i:number)=><li key={i}>{String(x)}</li>)}</ul></div>}
    {limitations.length>0&&<div className="analysis-section"><h3>ML limitations</h3><ul>{limitations.slice(0,20).map((x:any,i:number)=><li key={i}>{String(x)}</li>)}</ul></div>}
    {Array.isArray(result.data_quality?.checks)&&result.data_quality.checks.length>0&&<div className="analysis-section"><h3>Validation checks</h3><ul>{result.data_quality.checks.slice(0,30).map((check:any,i:number)=><li key={check.check_id||i}><strong>{pretty(String(check.status||"not reported"))}:</strong> {String(check.message||check.check_id||"Validation check")} {typeof check.count==="number"?`(${check.count})`:""}</li>)}</ul></div>}
    <p className="inline-note">Numerical values and anomaly calculations originate from the deterministic ML service. The LLM explanation follows below.</p>
  </section>;
}

function ValidationLab({ result, datasetName }: { result: ApiResult; datasetName: string }) {
  const ml = result.ml_analysis || {};
  const quality = ml.data_quality || {};
  const checks = Array.isArray(quality.checks) ? quality.checks : [];
  const anomalies = Array.isArray(ml.anomalies) ? ml.anomalies : [];
  const hypotheses = Array.isArray(ml.hypotheses) ? ml.hypotheses : [];
  const evidence = Array.isArray(ml.evidence) ? ml.evidence : [];
  const limitations = Array.isArray(ml.limitations) ? ml.limitations : [];
  const count = (status: string) => checks.filter((item: any) => String(item.status || "").toLowerCase() === status).length;
  return <div className="analysis-card">
    <div className="eyebrow">VALIDATION LAB · EVIDENCE REVIEW</div>
    <h2>Review what the analysis actually verified</h2>
    <p className="analysis-summary">This lab exposes the deterministic ML service's returned checks and evidence. It does not turn a model hypothesis into a confirmed equipment fault.</p>
    <div className="dataset-profile">
      <div className="dataset-profile-head"><h4>Analysis under review</h4><span>{String(ml.analysis_status || "status unavailable").toUpperCase()}</span></div>
      <p><strong>{datasetName}</strong> · Plant {result.plant_id || "not specified"} · {ml.interval?.row_count ?? ml.data_quality?.rows ?? "Unknown"} rows inspected</p>
      <p className="inline-note">The validation results below come from the deterministic ML response. No operational log file was supplied through the current upload endpoint.</p>
    </div>
    <div className="metric-grid">
      <div className="metric-card"><span>Validation checks</span><strong>{checks.length}</strong></div>
      <div className="metric-card"><span>Warnings</span><strong>{count("warning")}</strong></div>
      <div className="metric-card"><span>Failures</span><strong>{count("fail")}</strong></div>
      <div className="metric-card"><span>Detected anomalies</span><strong>{anomalies.length}</strong></div>
    </div>
    <section className="analysis-section">
      <h3>Data-quality checks</h3>
      {checks.length ? <ul>{checks.map((item: any, i: number) => <li key={item.check_id || i}><strong>{pretty(String(item.status || "not reported"))}:</strong> {String(item.message || item.check_id || "Validation check")} {typeof item.count === "number" ? `(${item.count})` : ""}</li>)}</ul> : <p>The ML response did not include individual validation checks. Review its data-quality status: <strong>{String(quality.status || "not reported")}</strong>.</p>}
    </section>
    <section className="analysis-section"><h3>Model findings and supporting evidence</h3>
      {anomalies.length ? <ul>{anomalies.slice(0, 30).map((item: any, i: number) => <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>)}</ul> : <p>No anomaly records were returned by the ML service.</p>}
      {hypotheses.length > 0 && <><h4>Possible contributing factors (not confirmed faults)</h4><ul>{hypotheses.slice(0, 20).map((item: any, i: number) => <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>)}</ul></>}
      {evidence.length > 0 && <><h4>Evidence returned by the ML service</h4><ul>{evidence.slice(0, 30).map((item: any, i: number) => <li key={i}>{String(item)}</li>)}</ul></>}
    </section>
    <section className="analysis-section">
      <h3>Operational log cross-check</h3>
      <p>No operational log upload is currently part of the existing API contract. Compare the timestamps and devices above with inverter alarms, maintenance records and site operator logs.</p>
      <p><strong>Important:</strong> If no matching log entry exists, mark the finding as unexplained and investigate it. Absence of a log entry is not proof that the event did not occur.</p>
    </section>
    {limitations.length > 0 && <section className="analysis-section"><h3>Limitations to consider</h3><ul>{limitations.slice(0, 20).map((item: any, i: number) => <li key={i}>{String(item)}</li>)}</ul></section>}
    <p className="inline-note">Validation status describes the checks returned by the current ML pipeline; it is not independent field verification. Confirm equipment conditions with site telemetry and qualified personnel.</p>
  </div>;
}

function AnalysisResponse({ result }: { result: ApiResult }) {
  const a = result.analysis;
  const sections: Array<[string, string[] | undefined, string]> = [
    ["What the readings tell us", a.observations, "No observations were returned."],
    ["Possible explanations", a.possible_causes, "No supported causes were identified from the supplied information."],
    ["Evidence considered", a.supporting_evidence, "The model did not identify specific supporting evidence."],
    ["Recommended checks", a.recommended_checks, "No checks were returned. Review the input data and try again."],
    ["Limitations and uncertainty", a.limitations, "No limitations were reported by the model."],
  ];
  return <div className="assistant-response">
    {result.ml_analysis && <MlAnalysisResponse result={result.ml_analysis}/>}
    <div className="analysis-topline">
      <div><div className="eyebrow">ANALYSIS RESPONSE</div><div className="analysis-meta">{result.plant_id || "Solar plant"}{result.model ? " · " + result.model : ""}</div></div>
      <span className={"confidence-pill " + a.confidence}>{pretty(a.confidence || "insufficient_evidence") + " confidence"}</span>
    </div>
    <p className="analysis-summary">{a.summary || "The model did not return a summary."}</p>
    <div className="analysis-grid">
      {sections.map(([title,items,fallback]) => <section className="analysis-section" key={title}><h3>{title}</h3><ul>{listOrFallback(items,fallback).map((item,i)=><li key={i}>{pretty(item)}</li>)}</ul></section>)}
    </div>
    <p className="inline-note" style={{marginTop:16}}>AI-generated explanation · Verify hypotheses with plant telemetry and qualified operators before taking action.</p>
  </div>;
}

export default function App() {
  const [apiBase, setApiBase] = useState(getApiBase);
  const [theme, setTheme] = useState<"light"|"dark">("light");
  const [page, setPage] = useState<"overview"|"data"|"validation"|"report"|"assistant">("overview");
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customApi, setCustomApi] = useState(getApiBase);
  const [plantId, setPlantId] = useState("");
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
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
          .then(async user=>{setAuthed(true);setUserName(user.name);setEmail(user.email);setBusinessName(user.business_name||"");const history=await loadStoredAnalyses(getApiBase(),token);setTurns(history);setSelectedTurnId(history[history.length-1]?.id||"");})
          .catch(()=>{localStorage.removeItem("solarsleuth_access_token");setAccessToken("");});
      }
    } catch {}
  }, []);
  useEffect(() => { document.documentElement.dataset.theme=theme; try{localStorage.setItem("solarsleuth_theme",theme)}catch{} },[theme]);
  const checkReady = useCallback(async () => {
    try { const r=await fetch(apiBase+"/ready",{signal:AbortSignal.timeout(8000)}); const j=await r.json(); const checks={ml:Boolean(j.ml_service_reachable),llm:Boolean(j.llm_api_reachable),model:Boolean(j.model_loaded)}; setServiceChecks(checks); setReady(r.ok&&checks.ml&&checks.llm?(checks.model?"ready":"warming"):"offline"); }
    catch { setServiceChecks({ml:false,llm:false,model:false}); setReady("offline"); }
  },[apiBase]);
  useEffect(() => { void checkReady(); const id=window.setInterval(()=>void checkReady(),15000); return ()=>window.clearInterval(id); },[checkReady]);

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
      setBusinessName(data.user.business_name||"");const history=await loadStoredAnalyses(apiBase,data.access_token);setTurns(history);setSelectedTurnId(history[history.length-1]?.id||"");setAuthed(true);setShowAuth(false);setPage("overview");
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
    if (datasetFile.size > 25 * 1024 * 1024) { setError("The selected file exceeds the 25 MiB upload limit."); return; }
    if (datasetFile.size === 0) { setError("The selected file is empty."); return; }
    const form=new FormData();
    form.append("file",datasetFile);
    form.append("plant_id",plantId.trim()||"unknown-plant");
    form.append("mode",uploadMode);
    if(uploadTimezone.trim())form.append("timezone",uploadTimezone.trim());
    if(uploadInterval.trim())form.append("interval_minutes",uploadInterval.trim());
    if(uploadSheet.trim())form.append("sheet_name",uploadSheet.trim());
    const id=Date.now().toString(36)+Math.random().toString(36).slice(2,7);
    setError("");setBusy(true);setUploadStage("running");setPage("assistant");
    setTurns(old=>[...old,{id,question:`Dataset analysis: ${datasetFile.name}`,createdAt:Date.now(),loading:true}]);
    try{
      const response=await fetch(apiBase+"/api/v1/analyze/upload",{method:"POST",headers:{Authorization:"Bearer "+accessToken},body:form,signal:AbortSignal.timeout(540000)});
      const raw=await response.json().catch(() => ({}));
      if(!response.ok)throw new Error(typeof raw.detail==="string"?raw.detail:raw.detail?.message || `Analysis request failed (HTTP ${response.status}).`);
      if(!raw.ml_analysis) throw new Error("The backend response did not include the deterministic ML result.");
      if(!raw.analysis || typeof raw.analysis !== "object") throw new Error("The backend response did not include a valid AI explanation.");
      setUploadStage("complete");
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,result:raw}:t));
      setSelectedTurnId(id);
    }catch(err){
      const msg=err instanceof Error?err.message:"Unable to complete dataset analysis.";
      setUploadStage("failed");
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,error:msg}:t));setError(msg);
    }finally{setBusy(false);}
  };
  const statusText=ready==="ready"?"ML + local AI ready":ready==="warming"?"ML connected · local AI model warming up":ready==="checking"?"Checking backend, ML and AI services":"Backend or a dependent service unavailable";
  const nav=[{id:"overview" as const,label:"Overview",icon:"◫"},{id:"data" as const,label:"Upload & analyse",icon:"⇧"},{id:"validation" as const,label:"Validation Lab",icon:"✓"},{id:"report" as const,label:"Reports",icon:"▤"},{id:"assistant" as const,label:"AI explanation",icon:"✳"}];
  const latestTurn = turns.find(t=>t.id===selectedTurnId && t.result) || turns.filter(t=>t.result).slice(-1)[0];

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
      <main className="workspace"><div className="workspace-head"><div><div className="breadcrumb">WORKSPACE <span>/</span> <b>{nav.find(n=>n.id===page)?.label}</b></div><h1>{page==="overview"?"Plant overview":page==="data"?"Upload & analyse":page==="validation"?"Validation Lab":page==="report"?"Reports":"AI explanation"}</h1><p>{page==="overview"?"A file-driven view of your latest analysis and local service readiness.":page==="data"?"Upload a CSV or Excel workbook for validation, deterministic analysis, and AI explanation.":page==="validation"?"Inspect data-quality checks, ML evidence and findings that need operational verification.":page==="report"?"Review and print the latest dataset-derived report.":"Read the detailed explanation generated from the latest uploaded dataset."}</p></div><div className="head-actions"><span className="plant-select-label">LATEST UPLOAD</span><div className="plant-select"><span className="plant-icon">☼</span><span><b>{turns.filter(t=>t.result).slice(-1)[0]?.question.replace("Dataset analysis: ","") || "No dataset analysed"}</b><small>{turns.filter(t=>t.result).length} successful analysis result(s)</small></span></div></div></div>
      <section className="controls-panel"><div><label>Service status</label><div className="engine-status"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</div><small className="service-breakdown">ML API: {serviceChecks.ml?"reachable":"unavailable"} · LLM API: {serviceChecks.llm?"reachable":"unavailable"} · Model: {serviceChecks.model?"loaded":"not loaded"}</small></div><div><label>Backend API</label><input aria-label="Backend API URL" value={customApi} onChange={e=>setCustomApi(e.target.value)} style={{maxWidth:280}}/></div><button className="small-action" onClick={()=>{const b=customApi.trim().replace(/\/$/,"");if(b){setApiBase(b);try{localStorage.setItem("solarsleuth_api_base",b)}catch{}setReady("checking");setTimeout(()=>void checkReady(),50)}}}>Connect</button></section>
      {page==="overview"&&<div className="analysis-card"><div className="eyebrow">FILE-DRIVEN SOLAR INTELLIGENCE</div><h2>{turns.some(t=>t.result)?"Latest plant analysis":"Start with your plant data"}</h2><p className="analysis-summary">{turns.some(t=>t.result)?"Your latest report is based on the uploaded dataset and deterministic ML output. Open Reports to review or save it.":"Upload a CSV or Excel workbook. SolarSleuth validates the file, maps supported columns, runs deterministic analysis, and asks the local AI model to explain the evidence."}</p><div className="metric-grid"><div className="metric-card"><span>Successful analyses</span><strong>{turns.filter(t=>t.result).length}</strong></div><div className="metric-card"><span>Service connection</span><strong>{ready==="ready"?"Ready":ready==="warming"?"Warming up":ready==="checking"?"Checking":"Unavailable"}</strong></div><div className="metric-card"><span>Latest dataset</span><strong>{turns.filter(t=>t.result).length? "Processed":"Not uploaded"}</strong></div></div><button className="primary-action" onClick={()=>setPage("data")}>Upload plant data ↗</button></div>}
      {page==="data"&&<div className="analysis-card"><div className="eyebrow">DATA INGESTION · CSV / XLSX</div><h2>Upload plant operating data</h2><p className="analysis-summary">The backend sends the file to the deterministic ML service first. Only its structured analysis is passed to the local LLM for explanation.</p><form onSubmit={uploadDataset} className="field-grid"><div className={"field-card upload-dropzone "+(dragActive?"drag-active":"")} style={{gridColumn:"1 / -1"}} onDragOver={e=>{e.preventDefault();setDragActive(true)}} onDragLeave={e=>{e.preventDefault();setDragActive(false)}} onDrop={e=>{e.preventDefault();setDragActive(false);const file=e.dataTransfer.files?.[0];if(file){setDatasetFile(file);setError("");setUploadStage("idle");}}}><label htmlFor="datasetFile">Operating data file</label><input id="datasetFile" type="file" accept=".csv,.xlsx" onChange={e=>{setDatasetFile(e.target.files?.[0]||null);setError("");setUploadStage("idle");}} required/><small>Drop a CSV or XLSX here, or choose a file · Maximum 25 MiB · One operating-data file per request</small>{datasetFile&&<div className="selected-file"><strong>{datasetFile.name}</strong><span>{(datasetFile.size/1024/1024).toFixed(2)} MiB</span><button type="button" className="small-action" onClick={()=>{setDatasetFile(null);setUploadStage("idle");}}>Remove</button></div>}</div>
<div className="field-card"><label htmlFor="plantId">Plant identifier (optional)</label><input id="plantId" value={plantId} maxLength={128} onChange={e=>setPlantId(e.target.value)} placeholder="Enter a plant identifier"/><small>Used as report metadata; measurements always come from the uploaded file.</small></div><div className="field-card"><label htmlFor="uploadMode">Analysis mode</label><select id="uploadMode" value={uploadMode} onChange={e=>setUploadMode(e.target.value)}><option value="auto">Automatic</option><option value="snapshot">Snapshot</option><option value="full">Full time-series</option></select></div><div className="field-card"><label htmlFor="uploadTimezone">IANA timezone (optional)</label><input id="uploadTimezone" value={uploadTimezone} onChange={e=>setUploadTimezone(e.target.value)} placeholder="Asia/Kolkata"/></div><div className="field-card"><label htmlFor="uploadInterval">Interval minutes (optional)</label><input id="uploadInterval" type="number" min="0.01" step="any" value={uploadInterval} onChange={e=>setUploadInterval(e.target.value)} placeholder="Auto-detect"/></div><div className="field-card"><label htmlFor="uploadSheet">Excel sheet name (optional)</label><input id="uploadSheet" value={uploadSheet} onChange={e=>setUploadSheet(e.target.value)} placeholder="First sheet by default"/></div><div style={{gridColumn:"1 / -1"}}><button className="primary-action" type="submit" disabled={busy||!datasetFile}>{busy?<><span className="inline-spinner" aria-hidden="true"/> Analysing dataset…</>:"Upload and analyse ↗"}</button>{error&&<div className="inline-error" role="alert">{error}</div>}{uploadStage==="running"&&<p className="pipeline-status" role="status">Your file has been sent to the backend. Validation, deterministic ML analysis and local AI explanation are running in sequence.</p>}{uploadStage==="complete"&&<p className="pipeline-status success" role="status">Analysis completed. Review the ML evidence and AI explanation.</p>}{uploadStage==="failed"&&<p className="pipeline-status failed" role="status">The analysis could not be completed. Review the error above and retry when the services are ready.</p>}</div></form><p className="inline-note" style={{marginTop:14}}>The current HTTP integration accepts one operating-data file. The ML Python pipeline supports additional context inputs, but multi-file weather/device/forecast/event-log upload is not yet exposed here.</p><p className="inline-note">SolarSleuth is file-first: plant readings are never entered manually in the application.</p></div>}
      {page==="validation"&&(latestTurn?.result?.ml_analysis ? <ValidationLab result={latestTurn.result} datasetName={latestTurn.question.replace("Dataset analysis: ","")}/> : <div className="analysis-card analysis-empty"><div className="empty-icon">✓</div><h3>No analysis to validate yet</h3><p>Upload a CSV or Excel workbook first. The Validation Lab will show the data-quality checks and evidence returned by the deterministic ML service.</p><button className="primary-action" onClick={()=>setPage("data")}>Upload plant data ↗</button></div>)}
      {page==="report"&&<div className="analysis-card report"><div className="analysis-topline noprint"><div><div className="eyebrow">REPORT</div><h2>Latest analysis report</h2><p className="analysis-meta">Generated from the latest successful uploaded-dataset analysis.</p></div><button className="small-action" onClick={()=>window.print()} disabled={!turns.some(t=>t.result)}>Print / Save PDF</button></div>{turns.filter(t=>t.result).map(t=><button key={t.id} type="button" className="small-action" style={{margin:"0 8px 12px 0"}} onClick={()=>setSelectedTurnId(t.id)}>{t.question.replace("Dataset analysis: ","")} · {new Date(t.createdAt).toLocaleDateString()}</button>)}{turns.filter(t=>t.result&&t.id===latestTurn?.id).map(t=><div key={t.id} className="report-content"><div className="report-heading"><div className="eyebrow">SOLARSLEUTH · SOLAR PERFORMANCE INTELLIGENCE</div><h1>Plant performance analysis</h1><p>Dataset: {t.question.replace("Dataset analysis: ","")}</p><p>Generated: {new Date(t.createdAt).toLocaleString()}</p><p>Plant: {t.result!.plant_id || "Not specified"} · Mode: {t.result!.analysis_mode || "Not specified"}</p><p>Request ID: {t.result!.request_id || "Not provided"}</p></div><h3>Executive analysis</h3><AnalysisResponse result={t.result!}/></div>)}{!turns.some(t=>t.result)&&<div className="analysis-empty"><p>No successful analysis is available yet.</p><button className="primary-action" onClick={()=>setPage("data")}>Run an analysis ↗</button></div>}</div>}
      {page==="assistant"&&<><div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">LOCAL MODEL · QWEN</div><h2>AI explanation</h2><p className="analysis-meta">Detailed explanations are generated from the deterministic ML result returned by your uploaded dataset.</p></div><button className="small-action" onClick={()=>setTurns([])} disabled={busy}>Clear history</button></div><p className="analysis-meta">The browser sends files only to the application backend. Follow-up chat is not enabled until the backend exposes a dataset-grounded conversation endpoint.</p>{uploadStage==="running"&&<div className="pipeline-status" role="status"><span className="inline-spinner" aria-hidden="true"/> Processing upload → deterministic ML analysis → local AI explanation. Keep the services running.</div>}{uploadStage==="complete"&&<div className="pipeline-status success" role="status">Analysis completed successfully. The ML result and AI explanation are shown below.</div>}{uploadStage==="failed"&&<div className="pipeline-status failed" role="status">Analysis failed. See the message in the latest request below, then retry from Upload & analyse.</div>}</div><div className="assistant-history" style={{marginTop:18}}>{turns.length===0&&<div className="analysis-card analysis-empty"><div className="empty-icon">✳</div><h3>No analysis yet</h3><p>Upload a plant dataset to generate its deterministic analysis and local AI explanation.</p><button className="primary-action" onClick={()=>setPage("data")}>Upload a dataset ↗</button></div>}{turns.map(t=><div className="assistant-turn" key={t.id}><div className="user-question">{t.question}</div><div className="assistant-label"><span className="chat-avatar">✳</span>SolarSleuth · local AI</div>{t.loading?<div className="assistant-response"><p>Your upload is being processed by the backend. The deterministic ML service runs first, followed by the local AI explanation.</p><div className="loader" style={{marginTop:12}}/></div>:t.error?<div className="inline-error">{t.error}</div>:t.result?<AnalysisResponse result={t.result}/>:null}</div>)}</div></>}
      </main></div><footer className="app-footer">SolarSleuth is a prototype. Confirm model hypotheses against real telemetry and qualified operator checks. Account access uses expiring backend-issued tokens.</footer>
    </>}
  </>;
}
