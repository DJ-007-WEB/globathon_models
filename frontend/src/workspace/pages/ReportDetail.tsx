import { Link, useParams } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useAnalysisDetail, useWorkspace } from "../../state/WorkspaceContext";
import { FALLBACK_MODELS } from "../../types/backend";
import type { MlResult } from "../../types/ml";
import { formatInterval, formatKwh, formatNumber, formatUtc, humanize, isNumber } from "../../lib/format";
import { Card, Empty, EnergyKpis, ErrorNote, ExplanationView, Loading, PageHead, Pill, QualityBar, WaterfallChart } from "../ui";

function InputsSection({ ml }: { ml: MlResult }) {
  const roles = ml.input_roles ?? [];
  const rows = ml.column_mapping ?? [];
  const missing = ml.missing_required_fields ?? [];
  const unresolved = ml.unresolved_fields ?? [];
  if (!roles.length && !rows.length && !missing.length && !unresolved.length) return null;
  return (
    <Card title="Inputs, columns and units" icon="file-in">
      {roles.length > 0 && (
        <div className="roles">
          {roles.map((r) => (
            <div key={r.role} className={`role role-${r.status}`}>
              <small>{humanize(r.role)}</small>
              <b>{r.status === "used" ? "Used" : r.status === "unavailable" ? "Not used" : "Not supplied"}</b>
              <span>{r.source_file ? `${r.source_file}${r.sheet_name ? ` · sheet “${r.sheet_name}”` : ""}` : "—"}</span>
              {r.status === "used" && <span>{r.mapped_fields} mapped field{r.mapped_fields === 1 ? "" : "s"}{isNumber(r.coverage) ? ` · ${formatNumber(r.coverage * 100, 0)}% coverage` : ""}</span>}
              {r.reason && <span className="muted">{r.reason}</span>}
            </div>
          ))}
        </div>
      )}
      {missing.length > 0 && <div className="ws-alert ws-alert-warning"><Icon name="alert" /><span><b>Required inputs missing:</b> {missing.map(humanize).join(", ")}. Dependent metrics are unavailable.</span></div>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Input</th><th>Source column</th><th>Interpreted as</th><th>Unit</th><th>Conversion</th><th>Status</th></tr></thead>
            <tbody>{rows.map((row, i) => (
              <tr key={i} className={row.used ? "" : "row-muted"}>
                <td>{humanize(row.input || "")}</td><td><code>{row.source_column}</code>{row.sheet_name ? <small className="muted"> · {row.sheet_name}</small> : null}</td>
                <td>{row.canonical_role ? humanize(row.canonical_role) : "—"}{row.device_id ? ` · ${row.device_id}` : ""}</td>
                <td>{row.detected_unit || row.canonical_unit || "—"}{row.canonical_unit && row.detected_unit && row.canonical_unit !== row.detected_unit ? ` → ${row.canonical_unit}` : ""}</td>
                <td>{row.conversion || "—"}</td>
                <td><Pill status={row.used ? "used" : "neutral"}>{row.used ? "Used" : "Not used"}</Pill></td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
      {unresolved.length > 0 && <p className="ws-foot">Unresolved columns: {unresolved.join(", ")}</p>}
      <p className="ws-foot">Mapping and unit rules come from the deterministic ML schema registry. Columns marked “Not used” are kept for audit but excluded from calculations.</p>
    </Card>
  );
}

function AnomaliesSection({ ml }: { ml: MlResult }) {
  const runs = ml.anomaly_runs ?? [];
  const anomalies = ml.anomalies ?? [];
  return (
    <Card title={`Anomalies (${anomalies.length})`} icon="pulse">
      {!anomalies.length && !runs.length ? <Empty icon="check" title="No anomalies flagged" body="No interval met the anomaly checks." /> : (
        <>
          {runs.length > 0 && (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Device</th><th>From</th><th>To</th><th>Intervals</th><th>Checks</th><th>Logged events</th></tr></thead>
              <tbody>{runs.map((r, i) => <tr key={i}><td><b>{r.device_id}</b></td><td>{formatUtc(r.start_utc)}</td><td>{formatUtc(r.end_utc)}</td><td>{r.intervals}</td><td>{r.checks.map(humanize).join(", ")}</td><td>{r.overlapping_events?.length ? r.overlapping_events.join(", ") : "—"}</td></tr>)}</tbody>
            </table></div>
          )}
          <details className="details"><summary>Individual alert intervals ({anomalies.length})</summary>
            <ul className="evidence-list">{anomalies.slice(0, 200).map((a, i) => (
              <li key={i}><b>{a.device_id ?? "Plant"}</b> · {formatUtc(a.timestamp_utc)} — {a.message}
                {Object.keys(a.evidence || {}).length > 0 && <small className="muted"> ({Object.entries(a.evidence).map(([k, v]) => `${humanize(k)}: ${formatNumber(v, 2)}`).join(" · ")})</small>}</li>))}
            </ul>
            {anomalies.length > 200 && <p className="ws-foot">Showing the first 200 of {anomalies.length}.</p>}
          </details>
        </>
      )}
      <p className="ws-foot">Alerts indicate unusual behaviour, not root causes.</p>
    </Card>
  );
}

function HypothesesSection({ ml }: { ml: MlResult }) {
  const items = ml.hypotheses ?? [];
  return (
    <Card title={`Hypotheses (${items.length})`} icon="sparkle">
      {!items.length ? <Empty title="No hypotheses" body="No rule attached a possible contributing factor to the alert intervals." /> : (
        <div className="hyp-list">{items.slice(0, 50).map((h, i) => (
          <article key={i} className="hyp">
            <header><b>{h.label}</b><Pill status={h.status === "confirmed_event" ? "success" : h.status === "suspected" ? "suspected" : "neutral"}>{h.status === "confirmed_event" ? "Event confirmed" : humanize(h.status)}</Pill></header>
            <small className="muted">{h.interval?.device_id ?? "Plant"} · {formatUtc(h.interval?.timestamp_utc)}{isNumber(h.confidence) ? ` · rule confidence ${formatNumber(h.confidence, 2)}` : ""} · root cause {h.root_cause_confirmed ? "confirmed" : "not confirmed"}</small>
            {h.evidence?.length > 0 && <><h5>Evidence</h5><ul>{h.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul></>}
            {h.missing_evidence?.length > 0 && <><h5>Missing evidence</h5><ul className="muted">{h.missing_evidence.map((e, j) => <li key={j}>{e}</li>)}</ul></>}
          </article>))}
          {items.length > 50 && <p className="ws-foot">Showing 50 of {items.length}.</p>}
        </div>
      )}
      <p className="ws-foot">Hypotheses are not confirmed faults. Confirm them with an event log or a site inspection.</p>
    </Card>
  );
}

function DevicesSection({ ml }: { ml: MlResult }) {
  const items = ml.device_performance ?? [];
  if (!items.length) return null;
  const max = Math.max(1, ...items.map((d) => Math.max(d.actual_energy_kwh ?? 0, d.expected_energy_kwh ?? 0)));
  return (
    <Card title="Device performance" icon="layers">
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Device</th><th>Measured</th><th>Expected</th><th>Difference</th><th className="hide-sm">Measured vs expected</th></tr></thead>
        <tbody>{items.map((d) => (
          <tr key={d.device_id}><td><b>{d.device_id}</b></td><td>{formatKwh(d.actual_energy_kwh)}</td><td>{formatKwh(d.expected_energy_kwh)}</td>
            <td className={isNumber(d.deviation_kwh) && d.deviation_kwh < 0 ? "neg" : ""}>{formatKwh(d.deviation_kwh)}</td>
            <td className="hide-sm"><div className="dbar"><i className="dbar-exp" style={{ width: `${((d.expected_energy_kwh ?? 0) / max) * 100}%` }} /><i className="dbar-act" style={{ width: `${((d.actual_energy_kwh ?? 0) / max) * 100}%` }} /></div></td></tr>))}
        </tbody>
      </table></div>
    </Card>
  );
}

export function AiPanel({ detail, base }: { detail: { request_id: string; result: { model: string; analysis: any } }; base: string }) {
  const { mode } = useWorkspace();
  const ex = detail.result.analysis;
  const fallback = FALLBACK_MODELS.has(detail.result.model);
  return (
    <Card className="ai-card" title="AI explanation" icon="sparkle" actions={<span className={`pill ${fallback ? "pill-warning" : "pill-info"}`}>{mode === "preview" ? "Not generated" : fallback ? "Evidence-only fallback" : `Local model · ${detail.result.model}`}</span>}>
      {!ex ? <Empty icon="sparkle" title="No AI narrative" body={mode === "preview" ? "Synthetic preview reports include the ML result only. Create a workspace to see the local model explain your own report." : "The explanation is unavailable for this report."} />
        : <>
          {fallback && <div className="ws-alert ws-alert-warning"><Icon name="info" /><span>The local AI model was unavailable, so this text was assembled from the ML evidence only.</span></div>}
          <ExplanationView ex={ex} />
        </>}
      {mode === "live" && <Link className="btn btn-outline btn-sm" style={{ marginTop: 14 }} to={`${base}/assistant?report=${detail.request_id}`}><Icon name="message" />Ask a follow-up</Link>}
    </Card>
  );
}

export function ReportDetail() {
  const { requestId } = useParams();
  const { base, plants } = useWorkspace();
  const { detail, loading, error } = useAnalysisDetail(requestId);
  if (loading) return <Loading rows={4} />;
  if (error || !detail) return <><PageHead title="Report" /><ErrorNote message={error || "Report not found."} /><Link className="text-link" to={`${base}/reports`}>Back to reports</Link></>;
  const ml = detail.result.ml_analysis;
  const plant = plants.find((p) => p.plant_id === detail.plant_id);
  return (
    <div className="report">
      <PageHead eyebrow={`Report · ${plant?.name ?? detail.plant_id}`} title={detail.filename}
        body={<>{formatUtc(detail.created_at)} · {humanize(detail.analysis_mode || "—")} mode · <code>{detail.request_id}</code></>}
        actions={<><Pill status={detail.analysis_status} /><button type="button" className="btn btn-outline btn-sm" onClick={() => window.print()}><Icon name="printer" />Print</button></>} />
      {!ml ? <ErrorNote message="This report has no deterministic ML result." /> : (
        <>
          {ml.summary && <div className="ws-summary"><Icon name="info" /><p>{ml.summary}</p></div>}
          <div className="meta-strip">
            <span><small>Period</small>{formatUtc(ml.interval?.start_utc)} → {formatUtc(ml.interval?.end_utc)}</span>
            <span><small>Sampling</small>{formatInterval(ml.interval?.sampling_interval_seconds)}</span>
            <span><small>Devices</small>{formatNumber(ml.interval?.device_count, 0)}</span>
            <span><small>Rows</small>{formatNumber(ml.interval?.row_count, 0)}</span>
            <span><small>Method</small>{ml.method || "—"}</span>
          </div>
          <EnergyKpis ml={ml} />
          <div className="ws-grid-2 wide-left">
            <Card title="Energy waterfall" icon="waterfall"><WaterfallChart wf={ml.waterfall} />
              {ml.waterfall?.limitations?.length > 0 && <ul className="mini-list">{ml.waterfall.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>}</Card>
            <Card title="Data quality" icon="shield-check" actions={<Pill status={ml.data_quality?.status} />}>
              <QualityBar dq={ml.data_quality} />
              <ul className="check-rows">{(ml.data_quality?.checks ?? []).map((c) => <li key={c.check_id}><Pill status={c.status}>{humanize(c.status)}</Pill><span>{humanize(c.check_id)}<small className="muted">{c.message}</small></span></li>)}</ul>
              <Link className="text-link" to={`${base}/validation?report=${detail.request_id}`}>Open in Validation Lab <Icon name="arrow-right" /></Link>
            </Card>
          </div>
          <InputsSection ml={ml} />
          <AnomaliesSection ml={ml} />
          <HypothesesSection ml={ml} />
          <DevicesSection ml={ml} />
          {(ml.limitations?.length > 0 || ml.errors?.length > 0) && (
            <Card title="Limitations and errors" icon="info">
              <ul className="mini-list">{ml.limitations?.map((l, i) => <li key={i}>{l}</li>)}{ml.errors?.map((e, i) => <li key={`e${i}`} className="neg">{e.code}: {e.message}</li>)}</ul>
            </Card>
          )}
        </>
      )}
      <AiPanel detail={detail} base={base} />
    </div>
  );
}
