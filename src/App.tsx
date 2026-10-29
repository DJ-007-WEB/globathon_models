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
type ApiResult = { request_id?: string | null; plant_id?: string; model?: string; analysis: Analysis };
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

  useEffect(() => {
    try { const t=localStorage.getItem("solarsleuth_theme"); if(t==="light"||t==="dark")setTheme(t); const s=localStorage.getItem("solarsleuth_demo_session"); if(s){const u=JSON.parse(s);setAuthed(true);setUserName(u.name||"Demo Analyst");setEmail(u.email||"demo@solarsleuth.app");} } catch {}
  }, []);
  useEffect(() => { document.documentElement.dataset.theme=theme; try{localStorage.setItem("solarsleuth_theme",theme)}catch{} },[theme]);
  const checkReady = useCallback(async () => {
    try { const r=await fetch(apiBase+"/ready",{signal:AbortSignal.timeout(4500)}); const j=await r.json(); setReady(r.ok&&j.model_loaded ? "ready" : "offline"); }
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
  const quickPrompt=(q:string)=>{setQuestion(q);setPage("assistant");void submitAnalysis(undefined,q);};
  const statusText=ready==="ready"?"Local model ready":ready==="checking"?"Checking local model":"Model unavailable";
  const nav=[{id:"overview" as const,label:"Overview",icon:"◫"},{id:"data" as const,label:"Data upload",icon:"⇧"},{id:"analysis" as const,label:"Variance analysis",icon:"⌁"},{id:"class" as const,label:"Cause classification",icon:"◉"},{id:"valid" as const,label:"Validation lab",icon:"✓"},{id:"report" as const,label:"Investor report",icon:"▤"},{id:"why" as const,label:"Methodology",icon:"◇"},{id:"assistant" as const,label:"AI assistant",icon:"✳"}];

  return <>
    {showAuth&&<div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="authTitle" onClick={e=>{if(e.target===e.currentTarget)setShowAuth(false)}}><div className="auth-card"><button className="modal-close" aria-label="Close sign-in" onClick={()=>setShowAuth(false)}>×</button><div className="auth-brand"><BrandMark/><b>SolarSleuth</b></div><div className="eyebrow">DEMO WORKSPACE ACCESS</div><h2 id="authTitle">Your solar intelligence workspace.</h2>{authMode==="signin"&&<div className="demo-cred"><div><b>Demo credentials</b><span>demo@solarsleuth.app · Demo@1234</span></div><button className="small-action" type="button" onClick={()=>{setEmail("demo@solarsleuth.app");setPassword("Demo@1234")}}>Use demo login</button></div>}<div className="auth-tabs"><button type="button" className={authMode==="signin"?"on":""} onClick={()=>{setAuthMode("signin");setAuthError("")}}>Sign in</button><button type="button" className={authMode==="signup"?"on":""} onClick={()=>{setAuthMode("signup");setAuthError("")}}>Create account</button></div><form onSubmit={login}>{authMode==="signup"&&<><label htmlFor="authName">Your name</label><input id="authName" autoComplete="name" value={fullName} onChange={e=>setFullName(e.target.value)} placeholder="e.g. Alex Morgan"/></>}<label htmlFor="authEmail">Email address</label><input id="authEmail" type="email" autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/><label htmlFor="authPassword">Password</label><input id="authPassword" type="password" autoComplete={authMode==="signup"?"new-password":"current-password"} value={password} onChange={e=>setPassword(e.target.value)} placeholder={authMode==="signup"?"8+ characters, a letter and a number":"Enter your password"}/>{authMode==="signup"&&<><label htmlFor="authConfirm">Confirm password</label><input id="authConfirm" type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} placeholder="Repeat password"/></>}{authError&&<div className="auth-error" role="alert">{authError}</div>}<button className="btn btn-primary btn-lg btn-full" type="submit">{authMode==="signup"?"Create demo account ↗":"Enter demo workspace ↗"}</button></form><p className="inline-note">Browser-local demo authentication only. Do not use for sensitive data.</p></div></div>}
    {!authed ? <section id="landing" className="landing-shell">
      <header className="topbar landing-topbar"><a className="brand" href="#home"><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><button className="signin-btn" onClick={()=>setShowAuth(true)}>Sign in</button></div></header>
      <div className="hero-grid"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line"></span> SOLAR ASSET INTELLIGENCE · GLOBATHON 2026</div><h1>When output falls short,<br/>find the <span>reason behind it.</span></h1><p className="hero-lede">Turn solar plant readings into an evidence-aware explanation. Explore performance, review possible causes and keep uncertainty visible — with a local AI model running on your machine.</p><div className="hero-actions"><button className="btn btn-primary btn-lg" id="startdemo" onClick={startDemo}>Explore the live demo <span aria-hidden="true"> ↗ </span></button><a className="text-link" href="#how">See how it works <span> ↓ </span></a></div><div className="hero-proof"><div className="proof-avatars"><span>PV</span><span>AI</span><span>✓</span></div><div><b>Explainable by design</b><small>Local inference · Evidence-first explanations · Human verification</small></div></div></div><div className="hero-visual" aria-label="Illustrative solar performance visualization"><div className="visual-orbit orbit-one"></div><div className="visual-orbit orbit-two"></div><div className="sun-glow"></div><div className="solar-art"><div className="sun-disc"></div><div className="sun-ray ray-a"></div><div className="sun-ray ray-b"></div><div className="sun-ray ray-c"></div><div className="solar-hill hill-back"></div><div className="solar-hill hill-front"></div><div className="panel-grid">{Array.from({length:12},(_,i)=><span key={i}/>)}</div></div><div className="visual-caption">LOCAL AI · SOLAR PERFORMANCE INTELLIGENCE</div></div></div>
      <div className="trust-strip"><div><b>Local</b><span>on-device model inference</span></div><div><b>Evidence</b><span>structured observations</span></div><div><b>Human</b><span>verification stays essential</span></div><div><b>Private</b><span>no cloud AI dependency</span></div></div>
      <section className="landing-section" id="how"><div className="section-heading"><div><div className="eyebrow">FROM READINGS TO EVIDENCE</div><h2>A clearer view of every solar performance gap.</h2></div><p>Built for operators and analysts who need a useful explanation without confusing a model hypothesis with a confirmed fault.</p></div><div className="feature-grid"><article className="feature-card"><span className="feature-number">01 / OBSERVE</span><div className="feature-icon icon-sun">☼</div><h3>Bring the readings together</h3><p>Provide power, expected output, panel temperature and irradiance as the evidence for analysis.</p></article><article className="feature-card"><span className="feature-number">02 / EXPLAIN</span><div className="feature-icon icon-unknown">◌</div><h3>Keep uncertainty visible</h3><p>Separate observations from possible causes, checks and limitations in the model's response.</p></article><article className="feature-card"><span className="feature-number">03 / VERIFY</span><div className="feature-icon icon-validate">✓</div><h3>Act on evidence, not guesses</h3><p>Use recommendations as verification steps, not proof that a fault has occurred.</p></article></div></section>
      <footer className="site-footer"><span>SolarSleuth © 2026</span><span>Globathon · Solar Recovery Intelligence</span><span>Local prototype · Demo authentication</span></footer>
    </section> : <>
      <header className="topbar"><a className="brand" href="#home" onClick={e=>{e.preventDefault();setPage("overview")}}><BrandMark/><span className="brand-copy"><b>SolarSleuth</b><small>Performance intelligence</small></span></a><div className="topbar-right"><span className="environment-pill"><span className="status-dot"></span>{statusText}</span><button className="icon-btn theme-toggle" onClick={()=>setTheme(theme==="dark"?"light":"dark")} aria-label="Toggle theme"><span className="theme-symbol">{theme==="dark"?"☾":"☼"}</span></button><div className="avatar-wrap"><button className="avatar-btn" title="Account menu" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)}>{userName.charAt(0)}</button><div className={"user-menu "+(menuOpen?"":"hide")}><div className="um-name">{userName}</div><div className="um-email">{email}</div><button className="um-out" onClick={()=>{setMenuOpen(false);logout()}}>Sign out</button></div></div></div></header>
      <div className="app-shell"><aside className="sidebar"><div className="sidebar-label">WORKSPACE</div><nav className="side-nav">{nav.map(n=><button key={n.id} className={page===n.id?"on":""} onClick={()=>setPage(n.id)}><span>{n.icon}</span>{n.label}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-mini-icon">✳</div><div><b>{userName}</b><small>{email}</small></div><span className="live-dot"></span></div></aside>
      <main className="workspace"><div className="workspace-head"><div><div className="breadcrumb">WORKSPACE <span>/</span> <b>{nav.find(n=>n.id===page)?.label}</b></div><h1>{page==="overview"?"Plant overview":page==="data"?"Data upload":page==="analysis"?"Variance analysis":page==="class"?"Cause classification":page==="valid"?"Validation lab":page==="report"?"Investor report":page==="assistant"?"AI assistant":"Methodology"}</h1><p>{page==="overview"?"A quick view of current plant readings and local AI readiness.":page==="data"?"Review data-ingestion readiness and the inputs currently supported by the backend.":page==="analysis"?"Trace the current readings and request an evidence-aware explanation.":page==="class"?"Review possible explanations returned by the model as hypotheses, not confirmed faults.":page==="valid"?"Check service readiness and understand current validation boundaries.":page==="report"?"A readable summary of the latest model response.":page==="assistant"?"Ask for an explanation of the selected plant readings.":"Understand the boundaries of this prototype and its AI output."}</p></div><div className="head-actions"><span className="plant-select-label">ACTIVE PLANT</span><div className="plant-select"><span className="plant-icon">☼</span><span><b>{plantId||"Solar plant"}</b><small>{capacity} kW · Local test context</small></span><span className="chevron">⌄</span></div></div></div>
      <section className="controls-panel"><div><label>Service status</label><div className="engine-status"><span className={"status-dot "+(ready==="ready"?"":"")}></span>{statusText}</div></div><div><label>Backend API</label><input aria-label="Backend API URL" value={customApi} onChange={e=>setCustomApi(e.target.value)} style={{maxWidth:280}}/></div><button className="small-action" onClick={()=>{const b=customApi.trim().replace(/\/$/,"");if(b){setApiBase(b);try{localStorage.setItem("solarsleuth_api_base",b)}catch{}setReady("checking");setTimeout(()=>void checkReady(),50)}}}>Connect</button></section>
      {page==="overview"&&<><div className="metric-grid"><div className="metric-card"><span>Current output</span><strong>{currentPower} kW</strong><span>Entered plant reading</span></div><div className="metric-card"><span>Expected output</span><strong>{expectedPower} kW</strong><span>Reference value supplied</span></div><div className="metric-card"><span>Output difference</span><strong>{Number(expectedPower)-Number(currentPower)} kW</strong><span>Simple difference, not a diagnosis</span></div></div><div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">SOLAR RECOVERY INTELLIGENCE</div><h2>Ready to review the plant</h2><p className="analysis-meta">Enter readings in Plant analysis, then ask the local model to explain them.</p></div><span className="confidence-pill">Evidence first</span></div><button className="primary-action" onClick={()=>setPage("analysis")}>Open plant analysis <span>↗</span></button></div></>}
      {page==="analysis"&&<><div className="field-grid"><div className="field-card"><label htmlFor="plantId">Plant identifier</label><input id="plantId" value={plantId} onChange={e=>setPlantId(e.target.value)} placeholder="solar-plant-01"/></div><div className="field-card"><label htmlFor="capacity">Plant capacity (kW)</label><input id="capacity" type="number" min="0" value={capacity} onChange={e=>setCapacity(e.target.value)}/><small>Context only; not used to infer output.</small></div><div className="field-card"><label htmlFor="currentPower">Current power (kW)</label><input id="currentPower" type="number" min="0" value={currentPower} onChange={e=>setCurrentPower(e.target.value)}/></div><div className="field-card"><label htmlFor="expectedPower">Expected power (kW)</label><input id="expectedPower" type="number" min="0" value={expectedPower} onChange={e=>setExpectedPower(e.target.value)}/></div><div className="field-card"><label htmlFor="temperature">Panel temperature (°C)</label><input id="temperature" type="number" min="0" value={temperature} onChange={e=>setTemperature(e.target.value)}/></div><div className="field-card"><label htmlFor="irradiance">Irradiance (W/m²)</label><input id="irradiance" type="number" min="0" value={irradiance} onChange={e=>setIrradiance(e.target.value)}/></div></div><div className="analysis-card"><h2>What would you like to understand?</h2><p className="analysis-meta">The model receives the readings above and your question as context.</p><form className="assistant-composer" onSubmit={e=>{setPage("assistant");void submitAnalysis(e)}}><textarea className="question-input" value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask about the readings…" rows={2}/><button className="primary-action" type="submit" disabled={busy}>{busy?"Analysing…":"Analyse readings ↗"}</button></form>{error&&<div className="inline-error" role="alert">{error}</div>}<div className="suggestion-row">{["Explain the output difference","What should a technician check first?","What information is missing?"].map(q=><button className="suggestion-chip" key={q} onClick={()=>{setQuestion(q);setPage("assistant");void submitAnalysis(undefined,q)}}>{q}</button>)}</div></div></>}
      {page==="data"&&<div className="analysis-card"><div className="eyebrow">DATA INPUT</div><h2>Bring plant readings into the workspace</h2><p className="analysis-summary">The current backend contract accepts structured plant context and observations. CSV ingestion is not exposed by this API yet, so no upload will be claimed as processed.</p><button className="primary-action" onClick={()=>setPage("analysis")}>Enter readings manually ↗</button><p className="inline-note" style={{marginTop:14}}>Supported readings: current power, expected power, panel temperature and irradiance.</p></div>}
      {page==="class"&&<div className="analysis-card"><div className="eyebrow">HYPOTHESES · NOT CONFIRMED FAULTS</div><h2>Cause classification</h2>{turns.filter(t=>t.result).length===0?<div className="analysis-empty"><div className="empty-icon">◉</div><p>Run an analysis first to see possible causes returned by the model.</p><button className="primary-action" onClick={()=>setPage("analysis")}>Start analysis ↗</button></div>:<div className="analysis-grid">{turns.filter(t=>t.result).slice(-1).map(t=>(t.result!.analysis.possible_causes||[]).length?(t.result!.analysis.possible_causes.map((cause,i)=><section className="analysis-section" key={i}><h3>{pretty(cause)}</h3><p>Model-generated hypothesis. Verify against plant telemetry before treating it as a cause.</p></section>)):<section className="analysis-section" key={t.id}><h3>No supported cause returned</h3><p>The latest response did not identify a possible cause from the supplied information.</p></section>)}</div>}</div>}
      {page==="valid"&&<div className="analysis-card"><div className="eyebrow">SERVICE & VALIDATION</div><h2>Validation boundaries</h2><div className="metric-grid"><div className="metric-card"><span>Backend readiness</span><strong>{ready==="ready"?"Ready":ready==="checking"?"Checking":"Unavailable"}</strong></div><div className="metric-card"><span>LLM output schema</span><strong>Validated</strong><span>By the backend contract</span></div><div className="metric-card"><span>ML results</span><strong>Optional</strong><span>No teammate ML output is supplied by this form</span></div></div><p className="analysis-summary">This page reports connection and integration boundaries. It does not claim model accuracy or validate the physical correctness of an explanation.</p></div>}
      {page==="report"&&<div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">REPORT</div><h2>Latest analysis report</h2><p className="analysis-meta">Generated from the most recent successful local LLM response.</p></div><button className="small-action" onClick={()=>window.print()} disabled={!turns.some(t=>t.result)}>Print / Save PDF</button></div>{turns.filter(t=>t.result).slice(-1).map(t=><div key={t.id}><h3>{t.question}</h3><AnalysisResponse result={t.result!}/></div>)}{!turns.some(t=>t.result)&&<div className="analysis-empty"><p>No successful analysis is available yet.</p><button className="primary-action" onClick={()=>setPage("analysis")}>Run an analysis ↗</button></div>}</div>}
      {page==="assistant"&&<><div className="analysis-card"><div className="analysis-topline"><div><div className="eyebrow">LOCAL MODEL · QWEN</div><h2>Your analysis conversation</h2><p className="analysis-meta">Responses come from the local LLM API. The interface does not invent or fill in missing model output.</p></div><button className="small-action" onClick={()=>setTurns([])}>Clear conversation</button></div><form className="assistant-composer" onSubmit={e=>void submitAnalysis(e)}><textarea className="question-input" value={question} onChange={e=>setQuestion(e.target.value)} rows={2} placeholder="Ask about the current readings…"/><button className="primary-action" type="submit" disabled={busy}>{busy?"Thinking…":"Send ↗"}</button></form>{error&&<div className="inline-error" role="alert">{error}</div>}<div className="suggestion-row">{["Summarise the readings","List the main uncertainties","Suggest verification steps"].map(q=><button className="suggestion-chip" key={q} onClick={()=>void submitAnalysis(undefined,q)}>{q}</button>)}</div></div><div className="assistant-history" style={{marginTop:18}}>{turns.length===0&&<div className="analysis-card analysis-empty"><div className="empty-icon">✳</div><h3>No analysis yet</h3><p>Send a question to request a response from your local model.</p></div>}{turns.map(t=><div className="assistant-turn" key={t.id}><div className="user-question">{t.question}</div><div className="assistant-label"><span className="chat-avatar">✳</span>SolarSleuth · local AI</div>{t.loading?<div className="assistant-response"><p>Reviewing the supplied readings… This may take a little while while the local model generates its response.</p><div className="loader" style={{marginTop:12}}/></div>:t.error?<div className="inline-error">{t.error}</div>:t.result?<AnalysisResponse result={t.result}/>:null}</div>)}</div></>}
      {page==="why"&&<div className="analysis-card"><div className="eyebrow">METHOD & LIMITATIONS</div><h2>AI explains; operators verify.</h2><p className="analysis-summary">SolarSleuth forwards the provided plant context and readings to your local LLM API. The backend validates the response schema. The LLM is an explanation layer, not the source of measured data or deterministic ML predictions.</p><div className="analysis-grid"><section className="analysis-section"><h3>What this interface does</h3><ul><li>Connects to the backend at the configured API URL.</li><li>Submits current and expected power, panel temperature and irradiance.</li><li>Displays the model response with confidence and limitations.</li></ul></section><section className="analysis-section"><h3>What it does not do</h3><ul><li>It does not call the model directly or run ML calculations in the browser.</li><li>It does not treat a possible cause as a confirmed fault.</li><li>Demo sign-in is local-only and is not secure authentication.</li></ul></section></div></div>}
      </main></div><footer className="app-footer">SolarSleuth is a prototype. Confirm model hypotheses against real telemetry and qualified operator checks. Demo sign-in is not production authentication.</footer>
    </>}
  </>;
}
