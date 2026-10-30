import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

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
type Turn = { id: string; question: string; result?: ApiResult; error?: string; loading?: boolean };

const DEFAULT_API = "http://127.0.0.1:8001";
async function hashPassword(password: string, salt: string) { const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(salt+":"+password)); return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,"0")).join(""); }
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
    <div className="eyebrow">DETERMINISTIC ML · ${String(result.analysis_status||"unknown").toUpperCase()}</div>
    <h3>Calculated plant analysis</h3>
    <p>{result.summary || "The ML service returned a structured analysis."}</p>
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
    <p className="inline-note">Numerical values and anomaly calculations originate from the deterministic ML service. The LLM explanation follows below.</p>
  </section>;
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
  const [page, setPage] = useState<"overview"|"data"|"analysis"|"class"|"valid"|"report"|"why"|"assistant">("overview");
  const [showAuth, setShowAuth] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [userName, setUserName] = useState("Demo Analyst");
  const [email, setEmail] = useState("demo@solarsleuth.app");
  const [password, setPassword] = useState("Demo@1234");
  const [authMode, setAuthMode] = useState<"signin"|"signup">("signin");
  const [fullName, setFullName] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [ready, setReady] = useState<"checking"|"ready"|"offline">("checking");
  const [plantId, setPlantId] = useState("solar-plant-test-01");
  const [capacity, setCapacity] = useState("100");
  const [currentPower, setCurrentPower] = useState("62");
  const [expectedPower, setExpectedPower] = useState("90");
  const [temperature, setTemperature] = useState("48");
  const [irradiance, setIrradiance] = useState("800");
  const [question, setQuestion] = useState("Explain the current plant readings and what should be checked first.");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customApi, setCustomApi] = useState(getApiBase);
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [uploadMode, setUploadMode] = useState("auto");
  const [uploadTimezone, setUploadTimezone] = useState("");
  const [uploadInterval, setUploadInterval] = useState("");
  const [uploadSheet, setUploadSheet] = useState("");

  useEffect(() => {
    try { const t=localStorage.getItem("solarsleuth_theme"); if(t==="light"||t==="dark")setTheme(t); const s=localStorage.getItem("solarsleuth_demo_session"); if(s){const u=JSON.parse(s);setAuthed(true);setUserName(u.name||"Demo Analyst");setEmail(u.email||"demo@solarsleuth.app");} } catch {}
  }, []);
  useEffect(() => { document.documentElement.dataset.theme=theme; try{localStorage.setItem("solarsleuth_theme",theme)}catch{} },[theme]);
  const checkReady = useCallback(async () => {
    try { const r=await fetch(apiBase+"/ready",{signal:AbortSignal.timeout(4500)}); const j=await r.json(); setReady(r.ok&&j.ml_service_reachable&&j.llm_api_reachable ? "ready" : "offline"); }
    catch { setReady("offline"); }
  },[apiBase]);
  useEffect(() => { void checkReady(); const id=window.setInterval(()=>void checkReady(),15000); return ()=>window.clearInterval(id); },[checkReady]);

  const startDemo = () => { if(authed){setShowAuth(false);setPage("overview")}else setShowAuth(true); };
  const login = async (e: FormEvent) => {
    e.preventDefault(); setAuthError("");
    const cleanEmail=email.trim().toLowerCase();
    let signedInName = "Demo Analyst";
    if(authMode==="signup"){
      if(fullName.trim().length<2){setAuthError("Enter your name (at least 2 characters).");return;}
      if(!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]{2,}$/.test(cleanEmail)){setAuthError("Enter a valid email address.");return;}
      if(cleanEmail==="demo@solarsleuth.app"){setAuthError("That email is reserved for the demo account.");return;}
      if(password.length<8||!/[A-Za-z]/.test(password)||!/\\d/.test(password)){setAuthError("Use at least 8 characters with a letter and a number.");return;}
      if(password!==confirmPassword){setAuthError("The passwords do not match.");return;}
      try{
        const users=JSON.parse(localStorage.getItem("solarsleuth_users")||"{}");
        if(users[cleanEmail]){setAuthError("An account with this email already exists. Sign in instead.");return;}
        const salt=Math.random().toString(36).slice(2)+Date.now().toString(36);
        users[cleanEmail]={name:fullName.trim(),salt,hash:await hashPassword(password,salt)};
        localStorage.setItem("solarsleuth_users",JSON.stringify(users));
        setUserName(fullName.trim()); signedInName=fullName.trim();
      }catch{setAuthError("This browser could not save the account. Try the demo login.");return;}
    } else {
      if(!cleanEmail||!password){setAuthError("Enter your email and password.");return;}
      if(cleanEmail==="demo@solarsleuth.app"&&password==="Demo@1234"){setUserName("Demo Analyst");signedInName="Demo Analyst";}
      else{
        try{
          const users=JSON.parse(localStorage.getItem("solarsleuth_users")||"{}");
          const u=users[cleanEmail];
          if(!u||await hashPassword(password,u.salt)!==u.hash){setAuthError("Incorrect email or password.");return;}
          setUserName(u.name); signedInName=u.name;
        }catch{setAuthError("Unable to read this browser's demo account.");return;}
      }
    }
    setAuthed(true);
    try{localStorage.setItem("solarsleuth_demo_session",JSON.stringify({name:signedInName,email:cleanEmail,at:Date.now()}))}catch{}
    setShowAuth(false);setPage("overview");
  };
  const logout = () => { setAuthed(false);try{localStorage.removeItem("solarsleuth_demo_session")}catch{};setPage("overview"); };
  const requestBody = useMemo(() => ({
    plant_id: plantId.trim() || "solar-plant-test-01",
    plant_context: {capacity_kw:Number(capacity),location:"Test Site",user_question:question},
    observations: {current_power_kw:Number(currentPower),expected_power_kw:Number(expectedPower),panel_temperature_c:Number(temperature),irradiance_w_m2:Number(irradiance)},
    ml_results: {},
    retrieved_context: [],
  }),[plantId,capacity,currentPower,expectedPower,temperature,irradiance,question]);
  const submitAnalysis = async (e?: FormEvent, prompt?: string) => {
    e?.preventDefault();
    const q=(prompt ?? question).trim();
    if(!q){setError("Enter a question or describe what you want the model to explain.");return;}
    const nums=[capacity,currentPower,expectedPower,temperature,irradiance].map(Number);
    if(nums.some(n=>!Number.isFinite(n)||n<0)){setError("Enter valid non-negative numbers for all plant readings.");return;}
    setError("");setBusy(true);
    const id=Date.now().toString(36)+Math.random().toString(36).slice(2,7);
    const turn:Turn={id,question:q,loading:true};setTurns(old=>[...old,turn]);
    try{
      const body={...requestBody,plant_context:{...requestBody.plant_context,user_question:q}};
      const response=await fetch(apiBase+"/api/v1/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:AbortSignal.timeout(190000)});
      const raw=await response.json();
      if(!response.ok)throw new Error(typeof raw.detail==="string"?raw.detail:JSON.stringify(raw.detail||raw));
      if(!raw.analysis||typeof raw.analysis!=="object")throw new Error("The backend returned an unexpected response format.");
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,result:raw}:t));
    }catch(err){
      const msg=err instanceof Error?err.message:"Unable to reach the backend.";
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,error:msg}:t));
      setError(msg);
    }finally{setBusy(false);}
  };
  const uploadDataset = async (e: FormEvent) => {
    e.preventDefault();
    if(!datasetFile){setError("Choose a CSV or XLSX dataset first.");return;}
    const form=new FormData();
    form.append("file",datasetFile);
    form.append("plant_id",plantId.trim()||"unknown-plant");
    form.append("mode",uploadMode);
    if(uploadTimezone.trim())form.append("timezone",uploadTimezone.trim());
    if(uploadInterval.trim())form.append("interval_minutes",uploadInterval.trim());
    if(uploadSheet.trim())form.append("sheet_name",uploadSheet.trim());
    const id=Date.now().toString(36)+Math.random().toString(36).slice(2,7);
    setError("");setBusy(true);setPage("assistant");
    setTurns(old=>[...old,{id,question:`Dataset analysis: ${datasetFile.name}`,loading:true}]);
    try{
      const response=await fetch(apiBase+"/api/v1/analyze/upload",{method:"POST",body:form,signal:AbortSignal.timeout(360000)});
      const raw=await response.json();
      if(!response.ok)throw new Error(typeof raw.detail==="string"?raw.detail:JSON.stringify(raw.detail||raw));
      if(!raw.analysis||typeof raw.analysis!=="object"||!raw.ml_analysis)throw new Error("The backend response is missing the deterministic ML result or LLM explanation.");
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,result:raw}:t));
    }catch(err){
      const msg=err instanceof Error?err.message:"Unable to complete dataset analysis.";
      setTurns(old=>old.map(t=>t.id===id?{...t,loading:false,error:msg}:t));setError(msg);
    }finally{setBusy(false);}
  };
  const quickPrompt=(q:string)=>{setQuestion(q);setPage("assistant");void submitAnalysis(undefined,q);};
  const statusText=ready==="ready"?"ML + LLM services connected":ready==="checking"?"Checking local services":"One or more services unavailable";
  const nav=[{id:"overview" as const,label:"Overview",icon:"◫"},{id:"data" as const,label:"Upload & analyse",icon:"⇧"},{id:"report" as const,label:"Reports",icon:"▤"},{id:"assistant" as const,label:"AI explanation",icon:"✳"}];

  return <>
    {showAuth&&<div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="authTitle" onClick={e=>{if(e.target===e.currentTarget)setShowAuth(false)}}><div className="auth-card"><button className="modal-close" aria-label="Close sign-in" onClick={()=>setShowAuth(false)}>×</button><div className="auth-brand"><BrandMark/><b>SolarSleuth</b></div><div className="eyebrow">DEMO WORKSPACE ACCESS</div><h2 id="authTitle">Your solar intelligence workspace.</h2>{authMode==="signin"&&<div className="demo-cred"><div><b>Demo credentials</b><span>demo@solarsleuth.app · Demo@1234</span></div><button className="small-action" type="button" onClick={()=>{setEmail("demo@solarsleuth.app");setPassword("Demo@1234")}}>Use demo login</button></div>}<div className="auth-tabs"><button type="button" className={authMode==="signin"?"on":""} onClick={()=>{setAuthMode("signin");setAuthError("")}}>Sign in</button><button type="button" className={authMode==="signup"?"on":""} onClick={()=>{setAuthMode("signup");setAuthError("")}}>Create account</button></div><form onSubmit={login}>{authMode==="signup"&&<><label htmlFor="authName">Your name</label><input id="authName" autoComplete="name" value={fullName} onChange={e=>setFullName(e.target.value)} placeholder="e.g. Alex Morgan"/></>}<label htmlFor="authEmail">Email address</label><input id="authEmail" type="email" autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/><label htmlFor="authPassword">Password</label><input id="authPassword" type="password" autoComplete={authMode==="signup"?"new-password":"current-password"} value={password} onChange={e=>setPassword(e.target.value)} placeholder={authMode==="signup"?"8+ characters, a letter and a number":"Enter your password"}/>{authMode==="signup"&&<><label htmlFor="authConfirm">Confirm password</label><input id="authConfirm" type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} placeholder="Repeat password"/></>}{authError&&<div className="auth-error" role="alert">{authError}</div>}<button className="btn btn-primary btn-lg btn-full" type="submit">{authMode==="signup"?"Create demo account ↗":"Enter demo workspace ↗"}</button></form><p className="inline-note">Browser-local demo authentication only. Do not use for sensitive data.</p></div></div>}
    {!authed ? <section id="landing" className="landing-shell">
      <header className="topbar landing-topbar"><a className="brand" href="#home"><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><button className="signin-btn" onClick={()=>setShowAuth(true)}>Sign in</button></div></header>
      <div className="hero-grid"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line"></span> SOLAR ASSET INTELLIGENCE · GLOBATHON 2026</div><h1>When output falls short,<br/>find the <span>reason behind it.</span></h1><p className="hero-lede">Turn solar plant readings into an evidence-aware explanation. Explore performance, review possible causes and keep uncertainty visible — with a local AI model running on your machine.</p><div className="hero-actions"><button className="btn btn-primary btn-lg" id="startdemo" onClick={startDemo}>Explore the live demo <span aria-hidden="true"> ↗ </span></button><a className="text-link" href="#how">See how it works <span> ↓ </span></a></div><div className="hero-proof"><div className="proof-avatars"><span>PV</span><span>AI</span><span>✓</span></div><div><b>Explainable by design</b><small>Local inference · Evidence-first explanations · Human verification</small></div></div></div><div className="hero-visual" aria-label="Illustrative solar performance visualization"><div className="visual-orbit orbit-one"></div><div className="visual-orbit orbit-two"></div><div className="sun-glow"></div><div className="solar-art"><div className="sun-disc"></div><div className="sun-ray ray-a"></div><div className="sun-ray ray-b"></div><div className="sun-ray ray-c"></div><div className="solar-hill hill-back"></div><div className="solar-hill hill-front"></div><div className="panel-grid">{Array.from({length:12},(_,i)=><span key={i}/>)}</div></div><div className="visual-caption">LOCAL AI · SOLAR PERFORMANCE INTELLIGENCE</div></div></div>
      <div className="trust-strip"><div><b>Local</b><span>on-device model inference</span></div><div><b>Evidence</b><span>structured observations</span></div><div><b>Human</b><span>verification stays essential</span></div><div><b>Private</b><span>no cloud AI dependency</span></div></div>
      <section className="landing-section" id="how"><div className="section-heading"><div><div className="eyebrow">FROM READINGS TO EVIDENCE</div><h2>A clearer view of every solar performance gap.</h2></div><p>Built for operators and analysts who need a useful explanation without confusing a model hypothesis with a confirmed fault.</p></div><div className="feature-grid"><article className="feature-card"><span className="feature-number">01 / OBSERVE</span><div className="feature-icon icon-sun">☼</div><h3>Bring the readings together</h3><p>Upload a CSV or Excel workbook; the ML pipeline validates and maps the available measurements.</p></article><article className="feature-card"><span className="feature-number">02 / EXPLAIN</span><div className="feature-icon icon-unknown">◌</div><h3>Keep uncertainty visible</h3><p>Separate observations from possible causes, checks and limitations in the model's response.</p></article><article className="feature-card"><span className="feature-number">03 / VERIFY</span><div className="feature-icon icon-validate">✓</div><h3>Act on evidence, not guesses</h3><p>Use recommendations as verification steps, not proof that a fault has occurred.</p></article></div></section>
      <footer className="site-footer"><span>SolarSleuth © 2026</span><span>Globathon · Solar Recovery Intelligence</span><span>Local prototype · Demo authentication</span></footer>
    </section> : <>
      <header className="topbar"><a className="brand" href="#home" onClick={e=>{e.preventDefault();setPage("overview")}}><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className="status-dot"></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><div className="avatar-wrap"><button className="avatar-btn" title="Account menu" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)}>{userName.charAt(0)}</button><div className={"user-menu "+(menuOpen?"":"hide")}><div className="um-name">{userName}</div><div className="um-email">{email}</div><button className="um-out" onClick={()=>{setMenuOpen(false);logout()}}>Sign out</button></div></div></div></header>
      <div className="app-shell"><aside className="sidebar"><div className="sidebar-label">WORKSPACE</div><nav className="side-nav">{nav.map(n=><button key={n.id} className={page===n.id?"on":""} onClick={()=>setPage(n.id)}><span>{n.icon}</span>{n.label}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-mini-icon">✳</div><div><b>{userName}</b><small>{email}</small></div><span className="live-dot"></span></div></aside>
      <main className="workspace"><div className="workspace-head"><div><div className="breadcrumb">WORKSPACE <span>/</span> <b>{nav.find(n=>n.id===page)?.label}</b></div><h1>{page==="overview"?"Plant overview":page==="data"?"Data upload":page==="analysis"?"Variance analysis":page==="class"?"Cause classification":page==="valid"?"Validation lab":page==="report"?"Investor report":page==="assistant"?"AI assistant":"Methodology"}</h1><p>{page==="overview"?"A file-driven view of your latest analysis and local service readiness.":page==="data"?"Upload a CSV or Excel workbook for validation, deterministic analysis, and AI explanation.":page==="analysis"?"Trace the current readings and request an evidence-aware explanation.":page==="class"?"Review possible explanations returned by the model as hypotheses, not confirmed faults.":page==="valid"?"Check service readiness and understand current validation boundaries.":page==="report"?"A readable summary of the latest model response.":page==="assistant"?"Review the local AI explanation produced from your uploaded dataset.":"Understand the boundaries of this prototype and its AI output."}</p></div><div className="head-actions"><span className="plant-select-label">LATEST UPLOAD</span><div className="plant-select"><span className="plant-icon">☼</span><span><b>{turns.filter(t=>t.result).slice(-1)[0]?.question.replace("Dataset analysis: ","") || "No dataset analysed"}</b><small>{turns.filter(t=>t.result).length} successful analysis result(s)</small></span></div></div></div>
      <section className="controls-panel"><div><label>Service status</label><div className="engine-status"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</div></div><div><label>Backend API</label><input aria-label="Backend API URL" value={customApi} onChange={e=>setCustomApi(e.target.value)} style={{maxWidth:280}}/></div><button className="small-action" onClick={()=>{const b=customApi.trim().replace(/\/$/,"");if(b){setApiBase(b);try{localStorage.setItem("solarsleuth_api_base",b)}catch{}setReady("checking");setTimeout(()=>void checkReady(),50)}}}>Connect</button></section>
      {page==="overview"&&<div className="analysis-card"><div className="eyebrow">FILE-DRIVEN SOLAR INTELLIGENCE</div><h2>{turns.some(t=>t.result)?"Latest plant analysis":"Start with your plant data"}</h2><p className="analysis-summary">{turns.some(t=>t.result)?"Your latest report is based on the uploaded dataset and deterministic ML output. Open Reports to review or save it.":"Upload a CSV or Excel workbook. SolarSleuth validates the file, maps supported columns, runs deterministic analysis, and asks the local AI model to explain the evidence."}</p><div className="metric-grid"><div className="metric-card"><span>Successful analyses</span><strong>{turns.filter(t=>t.result).length}</strong></div><div className="metric-card"><span>Service connection</span><strong>{ready==="ready"?"Connected":ready==="checking"?"Checking":"Offline"}</strong></div><div className="metric-card"><span>Latest dataset</span><strong>{turns.filter(t=>t.result).length? "Processed":"Not uploaded"}</strong></div></div><button className="primary-action" onClick={()=>setPage("data")}>Upload plant data ↗</button></div>}
      {page==="analysis"&&<><div className="field-grid"><div className="field-card"><label htmlFor="plantId">Plant identifier</label><input id="plantId" value={plantId} onChange={e=>setPlantId(e.target.value)} placeholder="solar-plant-01"/></div><div className="field-card"><label htmlFor="capacity">Plant capacity (kW)</label><input id="capacity" type="number" min="0" value={capacity} onChange={e=>setCapacity(e.target.value)}/><small>Context only; not used to infer output.</small></div><div className="field-card"><label htmlFor="currentPower">Current power (kW)</label><input id="currentPower" type="number" min="0" value={currentPower} onChange={e=>setCurrentPower(e.target.value)}/></div><div className="field-card"><label htmlFor="expectedPower">Expected power (kW)</label><input id="expectedPower" type="number" min="0" value={expectedPower} onChange={e=>setExpectedPower(e.target.value)}/></div><div className="field-card"><label htmlFor="temperature">Panel temperature (°C)</label><input id="temperature" type="number" min="0" value={temperature} onChange={e=>setTemperature(e.target.value)}/></div><div className="field-card"><label htmlFor="irradiance">Irradiance (W/m²)</label><input id="irradiance" type="number" min="0" value={irradiance} onChange={e=>setIrradiance(e.target.value)}/></div></div><div className="analysis-card"><h2>What would you like to understand?</h2><p className="analysis-meta">The model receives the readings above and your question as context.</p><form className="assistant-composer" onSubmit={e=>{setPage("assistant");void submitAnalysis(e)}}><textarea className="question-input" value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask about the readings…" rows={2}/><button className="primary-action" type="submit" disabled={busy}>{busy?"Analysing…":"Analyse readings ↗"}</button></form>{error&&<div className="inline-error" role="alert">{error}</div>}<div className="suggestion-row">{["Explain the output difference","What should a technician check first?","What information is missing?"].map(q=><button className="suggestion-chip" key={q} onClick={()=>{setQuestion(q);setPage("assistant");void submitAnalysis(undefined,q)}}>{q}</button>)}</div></div></>}
      {page==="data"&&<div className="analysis-card"><div className="eyebrow">DATA INGESTION · CSV / XLSX</div><h2>Upload plant operating data</h2><p className="analysis-summary">The backend sends the file to the deterministic ML service first. Only its structured analysis is passed to the local LLM for explanation.</p><form onSubmit={uploadDataset} className="field-grid"><div className="field-card" style={{gridColumn:"1 / -1"}}><label htmlFor="datasetFile">Operating data file</label><input id="datasetFile" type="file" accept=".csv,.xlsx" onChange={e=>setDatasetFile(e.target.files?.[0]||null)} required/><small>CSV or XLSX · Maximum 25 MiB · One operating-data file per request</small></div><div className="field-card"><label htmlFor="uploadMode">Analysis mode</label><select id="uploadMode" value={uploadMode} onChange={e=>setUploadMode(e.target.value)}><option value="auto">Automatic</option><option value="snapshot">Snapshot</option><option value="full">Full time-series</option></select></div><div className="field-card"><label htmlFor="uploadTimezone">IANA timezone (optional)</label><input id="uploadTimezone" value={uploadTimezone} onChange={e=>setUploadTimezone(e.target.value)} placeholder="Asia/Kolkata"/></div><div className="field-card"><label htmlFor="uploadInterval">Interval minutes (optional)</label><input id="uploadInterval" type="number" min="0.01" step="any" value={uploadInterval} onChange={e=>setUploadInterval(e.target.value)} placeholder="Auto-detect"/></div><div className="field-card"><label htmlFor="uploadSheet">Excel sheet name (optional)</label><input id="uploadSheet" value={uploadSheet} onChange={e=>setUploadSheet(e.target.value)} placeholder="First sheet by default"/></div><div style={{gridColumn:"1 / -1"}}><button className="primary-action" type="submit" disabled={busy||!datasetFile}>{busy?"Running ML then LLM…":"Upload and analyse ↗"}</button>{error&&<div className="inline-error" role="alert">{error}</div>}</div></form><p className="inline-note" style={{marginTop:14}}>The current HTTP integration accepts one operating-data file. The ML Python pipeline supports additional context inputs, but multi-file weather/device/forecast/event-log upload is not yet exposed here.</p><p className="inline-note">SolarSleuth is file-first: plant readings are never entered manually in the application.</p></div>}
      {page==="class"&&<div className="analysis-card"><div className="eyebrow">HYPOTHESES · NOT CONFIRMED FAULTS</div><h2>Cause classification</h2>{turns.filter(t=>t.result).length===0?<div className="analysis-empty"><div className="empty-icon">◉</div><p>Run an analysis first to see possible causes returned by the model.</p><button className="primary-action" onClick={()=>setPage("data")}>Start analysis ↗</button></div>:<div className="analysis-grid">{turns.filter(t=>t.result).slice(-1).map(t=>(t.result!.analysis.possible_causes||[]).length?(t.result!.analysis.possible_causes.map((cause,i)=><section className="analysis-section" key={i}><h3>{pretty(cause)}</h3><p>Model-generated hypothesis. Verify against plant telemetry before treating it as a cause.</p></section>)):<section className="analysis-section" key={t.id}><h3>No supported cause returned</h3><p>The latest response did not identify a possible cause from the supplied information.</p></section>)}</div>}</div>}
      {page==="valid"&&<div className="analysis-card"><div className="eyebrow">SERVICE & VALIDATION</div><h2>Validation boundaries</h2><div className="metric-grid"><div className="metric-card"><span>Backend readiness</span><strong>{ready==="ready"?"Ready":ready==="checking"?"Checking":"Unavailable"}</strong></div><div className="metric-card"><span>LLM output schema</span><strong>Validated</strong><span>By the backend contract</span></div><div className="metric-card"><span>ML results</span><strong>Optional</strong><span>No teammate ML output is supplied by this form</span></div></div><p className="analysis-summary">This page reports connection and integration boundaries. It does not claim model accuracy or validate the physical correctness of an explanation.</p></div>}
      {page==="report"&&<div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">REPORT</div><h2>Latest analysis report</h2><p className="analysis-meta">Generated from the most recent successful local LLM response.</p></div><button className="small-action" onClick={()=>window.print()} disabled={!turns.some(t=>t.result)}>Print / Save PDF</button></div>{turns.filter(t=>t.result).slice(-1).map(t=><div key={t.id}><h3>{t.question}</h3><AnalysisResponse result={t.result!}/></div>)}{!turns.some(t=>t.result)&&<div className="analysis-empty"><p>No successful analysis is available yet.</p><button className="primary-action" onClick={()=>setPage("data")}>Run an analysis ↗</button></div>}</div>}
      {page==="assistant"&&<><div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">LOCAL MODEL · QWEN</div><h2>Your analysis conversation</h2><p className="analysis-meta">Responses come from the local LLM API. The interface does not invent or fill in missing model output.</p></div><button className="small-action" onClick={()=>setTurns([])}>Clear conversation</button></div><p className="analysis-meta">This view presents the explanation generated for the uploaded dataset. Follow-up chat requires a dedicated backend conversation endpoint; the frontend will not send fabricated manual readings.</p></div><div className="assistant-history" style={{marginTop:18}}>{turns.length===0&&<div className="analysis-card analysis-empty"><div className="empty-icon">✳</div><h3>No analysis yet</h3><p>Send a question to request a response from your local model.</p></div>}{turns.map(t=><div className="assistant-turn" key={t.id}><div className="user-question">{t.question}</div><div className="assistant-label"><span className="chat-avatar">✳</span>SolarSleuth · local AI</div>{t.loading?<div className="assistant-response"><p>Reviewing the supplied readings… This may take a little while while the local model generates its response.</p><div className="loader" style={{marginTop:12}}/></div>:t.error?<div className="inline-error">{t.error}</div>:t.result?<AnalysisResponse result={t.result}/>:null}</div>)}</div></>}
      {page==="why"&&<div className="analysis-card"><div className="eyebrow">METHOD & LIMITATIONS</div><h2>AI explains; operators verify.</h2><p className="analysis-summary">SolarSleuth forwards the provided plant context and readings to your local LLM API. The backend validates the response schema. The LLM is an explanation layer, not the source of measured data or deterministic ML predictions.</p><div className="analysis-grid"><section className="analysis-section"><h3>What this interface does</h3><ul><li>Connects to the backend at the configured API URL.</li><li>Submits current and expected power, panel temperature and irradiance.</li><li>Displays the model response with confidence and limitations.</li></ul></section><section className="analysis-section"><h3>What it does not do</h3><ul><li>It does not call the model directly or run ML calculations in the browser.</li><li>It does not treat a possible cause as a confirmed fault.</li><li>Demo sign-in is local-only and is not secure authentication.</li></ul></section></div></div>}
      </main></div><footer className="app-footer">SolarSleuth is a prototype. Confirm model hypotheses against real telemetry and qualified operator checks. Demo sign-in is not production authentication.</footer>
    </>}
  </>;
}
