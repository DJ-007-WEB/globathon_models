import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useAnalysisDetail, useWorkspace } from "../../state/WorkspaceContext";
import { formatInterval, formatNumber, formatUtc, humanize } from "../../lib/format";
import { Card, Empty, ErrorNote, Loading, PageHead, Pill, QualityBar } from "../ui";

const FILTERS = ["all", "pass", "warning", "fail", "not_checked"];

export function Validation() {
  const { base, analyses, analysesLoading, selectedPlantId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const scoped = useMemo(() => analyses.filter((a) => !selectedPlantId || a.plant_id === selectedPlantId), [analyses, selectedPlantId]);
  const reportId = params.get("report") || scoped[0]?.request_id || analyses[0]?.request_id;
  const { detail, loading, error } = useAnalysisDetail(reportId);
  const [filter, setFilter] = useState("all");
  if (analysesLoading) return <Loading />;
  if (!analyses.length) return (<><PageHead eyebrow="Plant data" title="Validation Lab" /><Card><Empty icon="flask" title="Nothing to validate yet" body="Upload an export to see its data-quality checks." /></Card></>);
  const ml = detail?.result.ml_analysis;
  const dq = ml?.data_quality;
  const checks = (dq?.checks ?? []).filter((c) => filter === "all" || c.status === filter);
  return (
    <>
      <PageHead eyebrow="Plant data" title="Validation Lab" body="Deterministic checks show whether the data can support the analysis."
        actions={<select className="select" value={reportId} onChange={(e) => setParams({ report: e.target.value })} aria-label="Report">
          {analyses.map((a) => <option key={a.request_id} value={a.request_id}>{a.filename} · {formatUtc(a.created_at)}</option>)}</select>} />
      {loading && <Loading rows={2} />}
      {error && <ErrorNote message={error} />}
      {ml && dq && (
        <>
          <div className="ws-grid-2">
            <Card title="Dataset status" icon="shield-check" actions={<Pill status={dq.status} />}>
              <p className="validity">{dq.valid ? <><Icon name="check" />Data can support the analysis</> : <><Icon name="alert" />Data cannot fully support the analysis</>}</p>
              <dl className="dl">
                <dt>Rows</dt><dd>{formatNumber(dq.rows, 0)}</dd>
                <dt>Sampling</dt><dd>{formatInterval(dq.sampling_interval_seconds)}</dd>
                <dt>Devices</dt><dd>{formatNumber(ml.interval?.device_count, 0)}</dd>
                <dt>Period</dt><dd>{formatUtc(ml.interval?.start_utc)} → {formatUtc(ml.interval?.end_utc)}</dd>
              </dl>
              <Link className="text-link" to={`${base}/reports/${detail!.request_id}`}>Open report <Icon name="arrow-right" /></Link>
            </Card>
            <Card title={`Checks (${dq.counts?.checks ?? 0})`} icon="layers"><QualityBar dq={dq} /></Card>
          </div>
          <Card title="Check results" icon="flask" actions={<div className="chips">{FILTERS.map((f) => <button key={f} type="button" className={`chip ${filter === f ? "active" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>{f === "all" ? "All" : humanize(f)}</button>)}</div>}>
            {!checks.length ? <p className="muted">No checks with this status.</p> : (
              <ul className="check-cards">{checks.map((c) => (
                <li key={c.check_id} className={`check-${c.status}`}>
                  <header><b>{humanize(c.check_id)}</b><Pill status={c.status}>{humanize(c.status)}</Pill></header>
                  <p>{c.message}</p>
                  <small className="muted">Count: {formatNumber(c.count, 0)}{c.affected_devices?.length ? ` · Devices: ${c.affected_devices.join(", ")}` : ""}</small>
                  {c.time_ranges?.length ? <small className="muted">{c.time_ranges.slice(0, 5).map((r) => `${formatUtc(r.start)} → ${formatUtc(r.end)}`).join(" · ")}{c.time_ranges.length > 5 ? ` · +${c.time_ranges.length - 5} more` : ""}</small> : null}
                </li>))}
              </ul>
            )}
          </Card>
          <div className="ws-grid-2">
            <Card title="Missing and unresolved fields" icon="alert">
              {ml.missing_required_fields?.length || ml.unresolved_fields?.length ? <>
                {ml.missing_required_fields?.length > 0 && <p><b>Missing required:</b> {ml.missing_required_fields.map(humanize).join(", ")}</p>}
                {ml.unresolved_fields?.length > 0 && <p className="muted"><b>Unresolved columns:</b> {ml.unresolved_fields.join(", ")}</p>}
              </> : <p className="muted">All required fields were found and every column was interpreted.</p>}
            </Card>
            <Card title="Limitations" icon="info">
              {(dq.limitations?.length || ml.limitations?.length) ? <ul className="mini-list">{[...(dq.limitations ?? []), ...(ml.limitations ?? [])].map((l, i) => <li key={i}>{l}</li>)}</ul> : <p className="muted">No limitations were reported.</p>}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
