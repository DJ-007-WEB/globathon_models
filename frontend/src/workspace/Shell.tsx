// Authenticated workspace shell: dark sidebar, top bar with plant selector, status and account menu.
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Icon, type IconName } from "../design/Icon";
import { Logo, LogoMark } from "../design/Logo";
import { getApiBase, setApiBase } from "../api/client";
import { useAuth } from "../state/AuthContext";
import { useWorkspace, WorkspaceProvider, type WorkspaceMode } from "../state/WorkspaceContext";
import { ThemeToggle } from "../marketing/MarketingLayout";
import { initials } from "../lib/format";

const MAIN: Array<{ to: string; label: string; icon: IconName; end?: boolean }> = [
  { to: "", label: "Overview", icon: "grid", end: true },
  { to: "/upload", label: "Upload & Analyse", icon: "upload" },
  { to: "/reports", label: "Reports", icon: "report" },
  { to: "/assistant", label: "AI Explanation", icon: "message" },
];
const PLANT_DATA: typeof MAIN = [
  { to: "/plants", label: "Plants", icon: "plant" },
  { to: "/validation", label: "Validation Lab", icon: "flask" },
];
const TITLES: Record<string, string> = { "": "Overview", upload: "Upload & Analyse", reports: "Reports", assistant: "AI Explanation", plants: "Plants", validation: "Validation Lab" };

function Sidebar({ collapsed, onToggle, mobileOpen, onClose }: { collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onClose: () => void }) {
  const { base, mode } = useWorkspace();
  const link = (item: (typeof MAIN)[number]) => (
    <NavLink key={item.label} to={base + item.to} end={item.end} className={({ isActive }) => `side-link ${isActive ? "active" : ""}`} title={collapsed ? item.label : undefined} onClick={onClose}>
      <Icon name={item.icon} /><span>{item.label}</span>
    </NavLink>
  );
  return (
    <>
      {mobileOpen && <div className="side-scrim" onClick={onClose} />}
      <aside className={`ws-side ${collapsed ? "collapsed" : ""} ${mobileOpen ? "open" : ""}`} aria-label="Workspace">
        <Link to="/" className="side-logo" aria-label="SolarSleuth home">{collapsed ? <LogoMark /> : <Logo tone="dark" />}</Link>
        <nav className="side-nav">
          {MAIN.map(link)}
          <span className="side-group">Plant data</span>
          {PLANT_DATA.map(link)}
        </nav>
        {mode === "preview" && !collapsed && <p className="side-note">Synthetic preview. Uploads, plants and chat are disabled. <Link to="/">Back to site</Link></p>}
        <button type="button" className="side-link side-collapse" onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse to rail"}>
          <Icon name="sidebar" /><span>Collapse to rail</span>
        </button>
      </aside>
    </>
  );
}

function StatusPill() {
  const { readyState, ready, refreshReady } = useWorkspace();
  const map = {
    checking: ["neutral", "Checking services"], ready: ["success", "Services ready"], warming: ["warning", "AI model loading"],
    "ai-error": ["danger", "AI model error"], "ai-offline": ["danger", "AI service offline"],
    offline: ["danger", "ML service offline"], preview: ["info", "Synthetic preview"],
  } as const;
  const [tone, label] = map[readyState];
  const title = ready ? `ML ${ready.ml_service_reachable ? "reachable" : "unreachable"} · LLM ${ready.llm_api_reachable ? "reachable" : "unreachable"}${ready.llm_status ? ` (${ready.llm_status})` : ""} · model ${ready.model_loaded ? "loaded" : "not loaded"}${ready.llm_error ? ` · ${ready.llm_error}` : ""} — click to re-check` : `${label} — click to re-check`;
  return <button type="button" className={`pill pill-${tone} status-pill`} title={title} onClick={() => void refreshReady()}>{label}</button>;
}

function AiNotice() {
  const { readyState, ready } = useWorkspace();
  if (readyState === "ready" || readyState === "checking") return null;
  const text = readyState === "offline" ? "The ML service is unreachable, so uploads will fail. Start it (port 8002) and click the status pill to re-check."
    : readyState === "ai-offline" ? "The local AI service (port 8000) is unreachable. Reports still run, but explanations will be the evidence-only fallback until it is started."
    : readyState === "ai-error" ? `The local AI model reported an error${ready?.llm_error ? `: ${ready.llm_error}` : ""}. Reports use the evidence-only fallback until the next successful generation.`
    : "The local AI model is not loaded yet. It loads in the background at startup, or on the first upload (this can take a few minutes on CPU).";
  return <div className={`ws-banner ws-banner-${readyState === "warming" ? "warn" : "danger"}`} role="status"><Icon name="alert" size={16} />{text}</div>;
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  const { mode } = useWorkspace();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [api, setApi] = useState(getApiBase());
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const name = mode === "preview" ? "Preview visitor" : user?.name || "Account";
  return (
    <div className="account" ref={ref}>
      <button type="button" className="avatar" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>{initials(name)}</button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-id"><b>{name}</b><small>{mode === "preview" ? "Read-only synthetic data" : `${user?.email ?? ""} · ${user?.business_name ?? ""}`}</small></div>
          {mode === "live" && (
            <form className="menu-api" onSubmit={(event) => { event.preventDefault(); setApiBase(api); window.location.reload(); }}>
              <label>Connection (API base)<input value={api} onChange={(event) => setApi(event.target.value)} /></label>
              <button type="submit" className="btn btn-outline btn-sm">Save &amp; reload</button>
            </form>
          )}
          <Link role="menuitem" className="menu-item" to="/" onClick={() => setOpen(false)}><Icon name="arrow-up-right" />Public site</Link>
          {mode === "live"
            ? <button role="menuitem" type="button" className="menu-item" onClick={() => { signOut(); navigate("/"); }}><Icon name="logout" />Sign out</button>
            : <Link role="menuitem" className="menu-item" to="/app"><Icon name="user" />Sign in to your workspace</Link>}
        </div>
      )}
    </div>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  const { base, plants, selectedPlantId, selectPlant } = useWorkspace();
  const { pathname } = useLocation();
  const parts = pathname.slice(base.length).split("/").filter(Boolean);
  const title = TITLES[parts[0] ?? ""] ?? "Workspace";
  return (
    <header className="ws-top">
      <button type="button" className="icon-btn ws-menu" aria-label="Open navigation" onClick={onMenu}><Icon name="menu" /></button>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={base}>Workspace</Link><Icon name="chevron-right" size={14} />
        {parts.length > 1 ? <><Link to={`${base}/${parts[0]}`}>{title}</Link><Icon name="chevron-right" size={14} /><span>{decodeURIComponent(parts[1])}</span></> : <span>{title}</span>}
      </nav>
      <div className="ws-top-actions">
        {plants.length > 0 && (
          <label className="plant-select"><Icon name="plant" size={16} /><span className="sr-only">Plant</span>
            <select value={selectedPlantId} onChange={(event) => selectPlant(event.target.value)}>
              {plants.map((plant) => <option key={plant.plant_id} value={plant.plant_id}>{plant.name}</option>)}
            </select>
          </label>
        )}
        <StatusPill />
        <ThemeToggle className="icon-btn ws-icon-btn" />
        <AccountMenu />
      </div>
    </header>
  );
}

function ShellFrame() {
  const { mode } = useWorkspace();
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("solarsleuth_sidebar") === "rail"; } catch { return false; } });
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => setMobileOpen(false), [pathname]);
  const toggle = () => setCollapsed((v) => { try { localStorage.setItem("solarsleuth_sidebar", v ? "full" : "rail"); } catch { /* ignore */ } return !v; });
  return (
    <div className={`ws ${collapsed ? "is-rail" : ""}`}>
      <a className="skip-link" href="#ws-main">Skip to content</a>
      <Sidebar collapsed={collapsed} onToggle={toggle} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="ws-body">
        <Topbar onMenu={() => setMobileOpen(true)} />
        {mode === "live" && <AiNotice />}
        {mode === "preview" && <div className="ws-banner"><Icon name="flask" size={16} />Synthetic data — generated scenarios processed by the real ML pipeline. No AI narrative; nothing here describes a real plant.</div>}
        <main id="ws-main" className="ws-main app-page-enter" key={pathname}><Outlet /></main>
      </div>
    </div>
  );
}

function AuthGate() {
  const { status, openAuth, sessionExpired, authModal } = useAuth();
  const { pathname } = useLocation();
  useEffect(() => {
    if (status === "signed-out" && !authModal.open) openAuth("signin", pathname);
  }, [status, authModal.open, openAuth, pathname]);
  if (status === "checking") return <div className="ws-gate"><span className="spinner" /> Restoring your session…</div>;
  if (status === "signed-out") return (
    <div className="ws-gate">
      <LogoMark size={40} />
      <h1>{sessionExpired ? "Your session expired" : "Sign in to open your workspace"}</h1>
      <p className="muted">Your plants and reports are private to your business.</p>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center" }}>
        <button type="button" className="btn btn-royal" onClick={() => openAuth("signin", pathname)}>Sign in</button>
        <Link className="btn btn-outline" to="/preview">Explore synthetic workspace</Link>
      </div>
    </div>
  );
  return <WorkspaceProvider mode="live"><ShellFrame /></WorkspaceProvider>;
}

export function WorkspaceShell({ mode }: { mode: WorkspaceMode }) {
  if (mode === "preview") return <WorkspaceProvider mode="preview"><ShellFrame /></WorkspaceProvider>;
  return <AuthGate />;
}
