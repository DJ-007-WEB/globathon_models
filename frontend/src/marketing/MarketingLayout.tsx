// Public site shell: sticky dark header (transparent over the home hero), progress line, mobile sheet, footer.
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../design/Icon";
import { Logo } from "../design/Logo";
import { NAV } from "../content/site";
import { useAuth } from "../state/AuthContext";
import { useTheme } from "../state/ThemeContext";

export function ThemeToggle({ className = "icon-btn" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  return (
    <button type="button" className={className} onClick={toggle} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title={theme === "dark" ? "Light theme" : "Dark theme"}>
      <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
    </button>
  );
}

/** "Open workspace" goes straight in when signed in, otherwise opens the sign-in modal. */
export function useOpenWorkspace() {
  const { status, openAuth } = useAuth();
  const navigate = useNavigate();
  return (mode: "signin" | "signup" = "signin") => {
    if (status === "signed-in") navigate("/app");
    else openAuth(mode, "/app");
  };
}

function ProgressLine() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (ref.current) ref.current.style.transform = `scaleX(${max > 0 ? Math.min(1, window.scrollY / max) : 0})`;
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); cancelAnimationFrame(frame); };
  }, []);
  return <div className="progress-line" ref={ref} aria-hidden="true" style={{ transform: "scaleX(0)" }} />;
}

function Header() {
  const { pathname } = useLocation();
  const onHero = pathname === "/";
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const openWorkspace = useOpenWorkspace();
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = ""; window.removeEventListener("keydown", onKey); };
  }, [menuOpen]);
  return (
    <>
      <header className={`mk-header ${onHero ? "on-hero" : ""} ${scrolled ? "scrolled" : ""}`}>
        <div className="container">
          <Link to="/" aria-label="SolarSleuth home"><Logo tone="dark" /></Link>
          <nav className="mk-nav" aria-label="Primary">
            {NAV.map((item) => <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>{item.label}</NavLink>)}
          </nav>
          <div className="mk-actions">
            <ThemeToggle />
            <button type="button" className="btn btn-lime" onClick={() => openWorkspace()}>
              <span>Open workspace</span><Icon name="arrow-up-right" />
            </button>
            <button type="button" className="icon-btn menu-btn" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
              <Icon name="menu" size={20} />
            </button>
          </div>
        </div>
      </header>
      {menuOpen && (
        <div className="mobile-sheet" role="dialog" aria-modal="true" aria-label="Site menu">
          <div className="row">
            <Logo tone="dark" />
            <button type="button" className="icon-btn" aria-label="Close menu" onClick={() => setMenuOpen(false)}><Icon name="x" size={20} /></button>
          </div>
          <Link className="link" to="/">Home</Link>
          {NAV.map((item) => <Link key={item.to} className="link" to={item.to}>{item.label}</Link>)}
          <button type="button" className="btn btn-lime" onClick={() => { setMenuOpen(false); openWorkspace(); }}>Open workspace <Icon name="arrow-up-right" /></button>
          <div className="row" style={{ marginTop: 18 }}><span style={{ color: "rgba(255,255,255,.7)", fontSize: 14 }}>Theme</span><ThemeToggle /></div>
        </div>
      )}
    </>
  );
}

function Footer() {
  const openWorkspace = useOpenWorkspace();
  return (
    <footer className="mk-footer">
      <div className="container">
        <div className="footer-grid">
          <div>
            <Logo tone="dark" />
            <p>Evidence-grounded performance analysis for solar plants. Deterministic numbers first; a local AI explains them.</p>
          </div>
          <div className="footer-col">
            <h4>Product</h4>
            <Link to="/capabilities">Capabilities</Link>
            <Link to="/demo">Demo</Link>
            <Link to="/preview">Synthetic workspace</Link>
            <button type="button" className="footer-link-btn" onClick={() => openWorkspace()}>Open workspace</button>
          </div>
          <div className="footer-col">
            <h4>Method</h4>
            <Link to="/trust">Trust &amp; method</Link>
            <Link to="/resources/data-requirements">Data requirements</Link>
            <Link to="/resources/how-it-works">How it works</Link>
            <Link to="/resources/method-and-limits">Method and limits</Link>
          </div>
          <div className="footer-col">
            <h4>Company</h4>
            <Link to="/about">About</Link>
            <Link to="/contact">Contact</Link>
            <a href="https://github.com/dj-007-web/globathon_models" target="_blank" rel="noreferrer">Source repository</a>
          </div>
        </div>
        <div className="footer-legal">
          <span>© 2026 SolarSleuth. Photography generated for SolarSleuth.</span>
          <span>Hypotheses are not confirmed faults. Synthetic demo data is labelled as such.</span>
        </div>
      </div>
    </footer>
  );
}

export function MarketingLayout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }); }, [pathname]);
  return (
    <div className="mk">
      <a className="skip-link" href="#main">Skip to content</a>
      <ProgressLine />
      <Header />
      <main id="main" key={pathname} className="page-enter"><Outlet /></main>
      <Footer />
    </div>
  );
}
