// Sign in / create account modal. Opens over any page; returns to the intended route on success.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../design/Icon";
import { Logo } from "../design/Logo";
import { useAuth } from "../state/AuthContext";

export function AuthModal() {
  const { authModal, closeAuth, openAuth, signIn, signUp } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", business_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const signup = authModal.mode === "signup";

  useEffect(() => {
    if (!authModal.open) return;
    setError("");
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") closeAuth(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    window.setTimeout(() => dialogRef.current?.querySelector<HTMLInputElement>("input")?.focus(), 30);
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [authModal.open, authModal.mode, closeAuth]);

  if (!authModal.open) return null;
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((current) => ({ ...current, [key]: event.target.value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (signup && form.password.length < 8) { setError("Use at least 8 characters for the password."); return; }
    setBusy(true);
    try {
      if (signup) await signUp(form);
      else await signIn(form.email, form.password);
      const target = authModal.returnTo || "/app";
      closeAuth();
      navigate(target);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally { setBusy(false); }
  }

  return (
    <div className="auth-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) closeAuth(); }}>
      <div className="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title" ref={dialogRef}>
        <aside className="auth-side">
          <img src="/images/pv-topdown.jpg" alt="" />
          <div className="auth-side-inner">
            <Logo tone="dark" />
            <div>
              <span className="eyebrow eyebrow-rule">Workspace</span>
              <h2>Reports your team can check line by line.</h2>
              <ul>
                <li><Icon name="check" size={16} />Deterministic ML numbers</li>
                <li><Icon name="check" size={16} />Hypotheses with evidence</li>
                <li><Icon name="check" size={16} />Local AI explanation</li>
              </ul>
            </div>
          </div>
        </aside>
        <div className="auth-main">
          <button type="button" className="auth-close" aria-label="Close" onClick={closeAuth}><Icon name="x" /></button>
          <div className="auth-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={!signup} className={!signup ? "active" : ""} onClick={() => openAuth("signin", authModal.returnTo)}>Sign in</button>
            <button type="button" role="tab" aria-selected={signup} className={signup ? "active" : ""} onClick={() => openAuth("signup", authModal.returnTo)}>Create account</button>
          </div>
          <h2 id="auth-title">{signup ? "Create your workspace" : "Welcome back"}</h2>
          <p className="muted">{signup ? "Your plants and reports are private to your business." : "Sign in to open your plants and reports."}</p>
          <form onSubmit={submit} className="auth-form">
            {signup && <>
              <label>Your name<input required value={form.name} onChange={set("name")} autoComplete="name" /></label>
              <label>Business name<input required value={form.business_name} onChange={set("business_name")} autoComplete="organization" /></label>
            </>}
            <label>Email<input required type="email" value={form.email} onChange={set("email")} autoComplete="email" /></label>
            <label>Password<input required type="password" minLength={signup ? 8 : undefined} value={form.password} onChange={set("password")} autoComplete={signup ? "new-password" : "current-password"} /></label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button type="submit" className="btn btn-royal" disabled={busy}>{busy ? <span className="spinner" /> : null}{signup ? "Create workspace" : "Sign in"}</button>
          </form>
          <Link className="text-link auth-preview" to="/preview" onClick={closeAuth}>Explore the workspace with synthetic data <Icon name="arrow-right" /></Link>
        </div>
      </div>
    </div>
  );
}
