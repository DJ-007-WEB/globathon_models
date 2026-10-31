// Workspace building blocks. Rendering only — every value comes from the saved ML result.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../design/Icon";
import { formatKwh, formatNumber, formatSigned, formatUtc, humanize, isNumber, statusTone } from "../lib/format";
import type { DataQuality, MlResult, Waterfall } from "../types/ml";
import type { Explanation } from "../types/backend";

export function PageHead({ eyebrow, title, body, actions }: { eyebrow?: string; title: string; body?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="ws-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {body && <p className="muted">{body}</p>}
      </div>
      {actions && <div className="ws-head-actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, icon, actions, children, className = "" }: { title?: ReactNode; icon?: IconName; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`ws-card ${className}`}>
      {(title || actions) && <header className="ws-card-head"><h2>{icon && <Icon name={icon} size={17} />}{title}</h2>{actions}</header>}
      {children}
    </section>
  );
}

export const Pill = ({ status, children }: { status: string | null | undefined; children?: ReactNode }) =>
  <span className={`pill pill-${statusTone(status)}`}>{children ?? humanize(status || "unknown")}</span>;

export function Empty({ icon = "info", title, body, action }: { icon?: IconName; title: string; body?: ReactNode; action?: ReactNode }) {
  return <div className="ws-empty"><span className="ws-empty-icon"><Icon name={icon} size={22} /></span><h3>{title}</h3>{body && <p className="muted">{body}</p>}{action}</div>;
}

export const ErrorNote = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div className="ws-alert ws-alert-danger" role="alert"><Icon name="alert" /><span>{message}</span>{onRetry && <button type="button" className="btn btn-outline btn-sm" onClick={onRetry}><Icon name="refresh" />Retry</button>}</div>
);

export const Loading = ({ rows = 3 }: { rows?: number }) => (
  <div className="ws-loading" aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ height: i ? 64 : 110 }} />)}</div>
);

export function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: ReactNode; tone?: "positive" | "negative" }) {
  return <div className="kpi"><small>{label}</small><strong className={tone ? `kpi-${tone}` : ""}>{value}</strong>{sub && <span>{sub}</span>}</div>;
}

export function EnergyKpis({ ml }: { ml: MlResult }) {
  const e = ml.energy;
  const dev = e?.deviation?.value_kwh;
  return (
    <div className="kpi-grid">
      <Kpi label="Forecast energy" value={formatKwh(e?.forecast?.value_kwh)} sub={e?.forecast?.status !== "available" ? humanize(e?.forecast?.status || "unavailable") : "From forecast input"} />
      <Kpi label="Expected energy" value={formatKwh(e?.expected?.value_kwh)} sub="Physics baseline" />
      <Kpi label="Actual energy" value={formatKwh(e?.actual?.value_kwh)} sub="Measured" />
      <Kpi label="Deviation" value={isNumber(dev) ? `${formatSigned(dev)} kWh` : "—"} tone={isNumber(dev) ? (dev < 0 ? "negative" : "positive") : undefined} sub={e?.deviation?.reason || "Actual vs reference"} />
    </div>
  );
}

/** Forecast → weather effect → expected → plant effect → actual, as floating bars. */
export function WaterfallChart({ wf }: { wf: Waterfall | undefined }) {
  if (!wf || wf.status === "unavailable") return <Empty icon="waterfall" title="Waterfall unavailable" body={wf?.reason || "The ML service did not return a waterfall for this dataset."} />;
  type Step = { label: string; value: number | null; from: number | null; to: number | null; kind: string };
  const f = wf.forecast_energy_kwh, x = wf.expected_energy_kwh, a = wf.actual_energy_kwh;
  const steps: Step[] = [
    { label: "Forecast", value: f, from: isNumber(f) ? 0 : null, to: f, kind: "forecast" },
    { label: "Weather effect", value: wf.weather_effect_kwh, from: f, to: x, kind: "weather" },
    { label: "Expected", value: x, from: isNumber(x) ? 0 : null, to: x, kind: "expected" },
    { label: "Plant effect", value: wf.plant_effect_kwh, from: x, to: a, kind: "plant" },
    { label: "Actual", value: a, from: isNumber(a) ? 0 : null, to: a, kind: "actual" },
  ];
  const nums = steps.flatMap((s) => [s.from, s.to]).filter(isNumber);
  const max = Math.max(1, ...nums);
  const min = Math.min(0, ...nums);
  // Zoom on the top of the bars so small effects stay visible; the axis note states this.
  const floor = Math.max(min, Math.min(...nums.filter((n) => n > 0)) * 0.85 || 0);
  const scale = (v: number) => ((v - floor) / (max - floor)) * 100;
  return (
    <div className="wf-chart">
      <div className="wf-bars">
        {steps.map((s) => {
          const ok = isNumber(s.from) && isNumber(s.to);
          const lo = ok ? Math.max(floor, Math.min(s.from!, s.to!)) : 0;
          const hi = ok ? Math.max(s.from!, s.to!) : 0;
          return (
            <div className="wf-col" key={s.label}>
              <span className="wf-val">{s.kind === "weather" || s.kind === "plant" ? formatSigned(s.value, 0) : formatNumber(s.value, 0)}</span>
              <div className="wf-area">
                {ok ? <i className={`wf-bar wf-${s.kind}`} style={{ bottom: `${scale(lo)}%`, height: `${Math.max(1.2, scale(hi) - scale(lo))}%` }} />
                  : <span className="wf-na">n/a</span>}
              </div>
              <small>{s.label}</small>
            </div>
          );
        })}
      </div>
      <p className="ws-foot">kWh · axis starts at {formatNumber(floor, 0)} kWh to keep small effects visible · {wf.reconciled ? "Reconciled within tolerance" : "Not reconciled"}{wf.reason ? ` · ${wf.reason}` : ""}</p>
    </div>
  );
}

export function QualityBar({ dq }: { dq: DataQuality | undefined }) {
  if (!dq?.counts) return null;
  const c = dq.counts, total = Math.max(1, c.checks);
  const parts = [["pass", c.pass], ["warning", c.warning], ["fail", c.fail], ["not_checked", c.not_checked]] as const;
  return (
    <div>
      <div className="seg-bar">{parts.map(([k, n]) => n > 0 && <i key={k} className={`seg-${k}`} style={{ width: `${(n / total) * 100}%` }} title={`${humanize(k)}: ${n}`} />)}</div>
      <div className="seg-legend">{parts.map(([k, n]) => <span key={k}><i className={`seg-${k}`} />{humanize(k)} <b>{n}</b></span>)}</div>
    </div>
  );
}

export function ExplanationView({ ex, compact = false }: { ex: Explanation; compact?: boolean }) {
  const sections: Array<[string, string[]]> = [
    ["Observations", ex.observations], ["Possible causes", ex.possible_causes], ["Supporting evidence", ex.supporting_evidence],
    ["Recommended checks", ex.recommended_checks], ["Limitations", ex.limitations],
  ];
  return (
    <div className="explanation">
      <p className="explanation-summary">{ex.summary}</p>
      <div className={compact ? "ex-grid compact" : "ex-grid"}>
        {sections.filter(([, items]) => items?.length).map(([title, items]) => (
          <div key={title}><h4>{title}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>
        ))}
      </div>
      <p className="ws-foot">Stated confidence: <b>{humanize(ex.confidence || "insufficient_evidence")}</b> · the narrative explains the ML result and does not add figures.</p>
    </div>
  );
}

export function ReportRow({ base, item, plantName }: { base: string; item: { request_id: string; filename: string; analysis_status: string; analysis_mode: string | null; created_at: string }; plantName?: string }) {
  return (
    <Link className="report-row" to={`${base}/reports/${encodeURIComponent(item.request_id)}`}>
      <span className="report-row-icon"><Icon name="report" /></span>
      <span className="report-row-main"><b>{item.filename}</b><small>{plantName ? `${plantName} · ` : ""}{humanize(item.analysis_mode || "—")} · {formatUtc(item.created_at)}</small></span>
      <Pill status={item.analysis_status} />
      <Icon name="chevron-right" />
    </Link>
  );
}
