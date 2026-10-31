// Sections shared between marketing pages.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Accordion } from "../design/Accordion";
import { Icon } from "../design/Icon";
import { Reveal } from "../design/Reveal";
import { FAQ, LIMITS, STAGES } from "../content/site";
import { previewDetail } from "../preview/source";
import { formatNumber, formatSigned, isNumber } from "../lib/format";
import type { Waterfall } from "../types/ml";
import { useOpenWorkspace } from "./MarketingLayout";

/** Hero card: the real ML waterfall of synthetic scenario 002, labelled as synthetic. */
export function HeroWaterfallCard() {
  const [wf, setWf] = useState<Waterfall | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    previewDetail("preview-002").then((detail) => setWf(detail.result.ml_analysis?.waterfall ?? null)).catch(() => setFailed(true));
  }, []);
  const rows = wf ? [
    { label: "Forecast", value: wf.forecast_energy_kwh, color: "var(--chart-forecast)", signed: false },
    { label: "Weather effect", value: wf.weather_effect_kwh, color: "var(--chart-weather)", signed: true },
    { label: "Expected", value: wf.expected_energy_kwh, color: "var(--chart-expected)", signed: false },
    { label: "Plant effect", value: wf.plant_effect_kwh, color: "var(--chart-plant)", signed: true },
    { label: "Actual", value: wf.actual_energy_kwh, color: "var(--chart-actual)", signed: false },
  ] : [];
  const max = Math.max(1, ...rows.map((row) => (isNumber(row.value) ? Math.abs(row.value) : 0)));
  return (
    <aside className="glass-card wf-card" aria-label="Example energy waterfall from synthetic data">
      <div className="wf-card-head"><span>Energy waterfall · kWh</span><span className="tag">Synthetic example</span></div>
      {failed && <p className="wf-note">The synthetic example could not be loaded.</p>}
      {!wf && !failed && <div className="skeleton" style={{ height: 150, borderRadius: 10 }} />}
      {rows.map((row) => (
        <div className="wf-row" key={row.label}>
          <span>{row.label}</span>
          <div className="wf-track"><div className="wf-fill" style={{ width: `${isNumber(row.value) ? Math.max(3, (Math.abs(row.value) / max) * 100) : 0}%`, background: row.color }} /></div>
          <b>{row.signed ? formatSigned(row.value, 0) : formatNumber(row.value, 0)}</b>
        </div>
      ))}
      {wf && <p className="wf-note">Generated scenario with an inverter outage, processed by the real ML pipeline. Weather and plant effects reconcile to the total deviation.</p>}
    </aside>
  );
}

export function PipelineExplorer() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setTimeout(() => setActive((current) => (current + 1) % STAGES.length), 6000);
    return () => window.clearTimeout(id);
  }, [active, paused]);
  const stage = STAGES[active];
  return (
    <section className="explorer" aria-labelledby="explorer-title">
      <div className="explorer-media">
        <img src="/images/switchgear-panel.jpg" alt="" loading="lazy" />
        <div className="explorer-caption">
          <span className="eyebrow eyebrow-rule">How it works</span>
          <h3>Seven stages, from an export file to a report you can defend.</h3>
        </div>
      </div>
      <div className="explorer-body">
        <div className="explorer-top">
          <h2 id="explorer-title">The analysis pipeline</h2>
          <button type="button" className="pause-btn" onClick={() => setPaused((value) => !value)} aria-pressed={paused}>
            <Icon name={paused ? "play" : "pause"} size={14} />{paused ? "Play" : "Pause"}
          </button>
        </div>
        <div className="stage-rail" role="tablist" aria-label="Pipeline stages">
          <span className="rail-fill" style={{ width: `calc((100% - 36px) * ${active / (STAGES.length - 1)})` }} />
          {STAGES.map((item, index) => (
            <button key={item.title} type="button" role="tab" aria-selected={index === active} aria-controls="stage-panel"
              className={`stage-node ${index < active ? "done" : ""} ${index === active ? "active" : ""}`}
              onClick={() => setActive(index)} title={item.short}>
              {index < active ? <Icon name="check" size={14} /> : index + 1}
            </button>
          ))}
        </div>
        <div className="stage-content" key={active} id="stage-panel" role="tabpanel" aria-live="polite">
          <span className="stage-tag">Stage {active + 1} of {STAGES.length} · {stage.short}</span>
          <h3>{stage.title}</h3>
          <p>{stage.body}</p>
          <div className="io">
            <span><small>In</small>{stage.input}</span><i aria-hidden="true" /><span className="out"><small>Out</small>{stage.output}</span>
          </div>
          <div className="specs">
            {stage.specs.map(([label, value]) => <div key={label}><small>{label}</small><b>{value}</b></div>)}
          </div>
          <p className="stage-source">Source: {stage.source}</p>
        </div>
      </div>
    </section>
  );
}

export function FaqSection({ title = "Questions, answered plainly." }: { title?: string }) {
  return (
    <section className="section">
      <div className="container faq-grid">
        <Reveal>
          <span className="eyebrow eyebrow-rule">FAQ</span>
          <h2 className="h2">{title}</h2>
          <p className="lead">Answers drawn from how the product actually behaves today.</p>
          <Link className="text-link" to="/resources">Read the method <Icon name="arrow-right" className="arrow" /></Link>
        </Reveal>
        <Reveal delay={120}><Accordion items={FAQ} /></Reveal>
      </div>
    </section>
  );
}

export function LimitsMarquee() {
  const [paused, setPaused] = useState(false);
  const half = Math.ceil(LIMITS.length / 2);
  const rows = [LIMITS.slice(0, half), LIMITS.slice(half)];
  return (
    <section className="section section-mist" aria-labelledby="limits-title">
      <div className="container marquee-head">
        <Reveal>
          <span className="eyebrow eyebrow-rule">Limits</span>
          <h2 className="h2" id="limits-title" style={{ marginTop: 10 }}>What SolarSleuth will not claim.</h2>
        </Reveal>
        <button type="button" className="pause-btn light-pause" onClick={() => setPaused((value) => !value)} aria-pressed={paused}>
          <Icon name={paused ? "play" : "pause"} size={14} />{paused ? "Play" : "Pause"}
        </button>
      </div>
      <div className={`marquee ${paused ? "paused" : ""}`}>
        {rows.map((row, rowIndex) => (
          <div key={rowIndex} className={`marquee-track ${rowIndex ? "reverse" : ""}`}>
            {[0, 1].map((copy) => row.map((limit) => (
              <article className="limit-card" key={`${copy}-${limit.text}`} aria-hidden={copy === 1 ? true : undefined}>
                <Icon name="quote" size={20} />
                <p>{limit.text}</p>
                <small>{limit.source}</small>
              </article>
            )))}
          </div>
        ))}
      </div>
    </section>
  );
}

export function CtaSection() {
  const openWorkspace = useOpenWorkspace();
  return (
    <section className="section">
      <div className="container cta-grid">
        <Reveal>
          <span className="eyebrow eyebrow-rule">Get started</span>
          <h2 className="h2" style={{ marginTop: 12 }}>See the reasoning, not just the result.</h2>
          <p className="lead">Every report shows the numbers, the checks behind them and what is still unknown — before any narrative.</p>
        </Reveal>
        <Reveal delay={120} className="cta-card">
          <h3>Start with your own export — or ours</h3>
          <p>Create a workspace and upload a CSV or XLSX export, or explore the read-only workspace built from synthetic scenarios.</p>
          <div className="actions">
            <button type="button" className="btn btn-royal" onClick={() => openWorkspace("signup")}>Create a workspace <Icon name="arrow-right" className="arrow" /></button>
            <Link className="text-link" to="/preview">Explore synthetic workspace <Icon name="arrow-right" /></Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function PageHero({ image, eyebrow, title, body, className = "" }: { image: string; eyebrow: string; title: string; body: string; className?: string }) {
  return (
    <section className={`page-hero ${className}`}>
      <img src={image} alt="" />
      <div className="container hero-in">
        <span className="eyebrow eyebrow-rule">{eyebrow}</span>
        <h1 className="display-2">{title}</h1>
        <p>{body}</p>
      </div>
    </section>
  );
}
