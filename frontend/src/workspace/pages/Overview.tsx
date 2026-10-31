import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useAnalysisDetail, useWorkspace } from "../../state/WorkspaceContext";
import { Card, Empty, EnergyKpis, ErrorNote, Loading, PageHead, Pill, QualityBar, ReportRow, WaterfallChart } from "../ui";
import { formatUtc } from "../../lib/format";

export function Overview() {
  const { base, mode, analyses, analysesLoading, analysesError, refreshAnalyses, selectedPlant, selectedPlantId, plants, plantsLoading } = useWorkspace();
  const scoped = useMemo(() => analyses.filter((a) => !selectedPlantId || a.plant_id === selectedPlantId), [analyses, selectedPlantId]);
  const latest = scoped[0];
  const { detail, loading, error } = useAnalysisDetail(latest?.request_id);
  const ml = detail?.result.ml_analysis ?? null;
  const plantName = (id: string) => plants.find((p) => p.plant_id === id)?.name;

  if (!plantsLoading && mode === "live" && plants.length === 0) {
    return (<><PageHead eyebrow="Overview" title="Welcome to SolarSleuth" />
      <Card><Empty icon="plant" title="Register your first plant" body="Plants group your uploads and reports. Register one, then upload an operating-data export."
        action={<Link className="btn btn-royal" to={`${base}/plants`}>Register a plant <Icon name="arrow-right" className="arrow" /></Link>} /></Card></>);
  }
  return (
    <>
      <PageHead eyebrow="Overview" title={selectedPlant?.name ?? "Overview"}
        body={latest ? <>Latest report: {latest.filename} · {formatUtc(latest.created_at)}</> : "No reports for this plant yet."}
        actions={mode === "live" && <Link className="btn btn-royal" to={`${base}/upload`}><Icon name="upload" />Upload & analyse</Link>} />
      {analysesError && <ErrorNote message={analysesError} onRetry={() => void refreshAnalyses()} />}
      {(analysesLoading || loading) && <Loading />}
      {error && <ErrorNote message={error} />}
      {!analysesLoading && !latest && !analysesError && (
        <Card><Empty icon="upload" title="No reports yet" body="Upload a CSV or XLSX export to produce the first report for this plant."
          action={mode === "live" ? <Link className="btn btn-royal" to={`${base}/upload`}>Upload data</Link> : undefined} /></Card>
      )}
      {ml && detail && (
        <>
          <EnergyKpis ml={ml} />
          <div className="ws-grid-2">
            <Card title="Energy waterfall" icon="waterfall" actions={<Link className="text-link" to={`${base}/reports/${detail.request_id}`}>Open report <Icon name="arrow-right" /></Link>}>
              <WaterfallChart wf={ml.waterfall} />
            </Card>
            <Card title="Needs attention" icon="alert">
              {ml.hypotheses?.length || ml.anomaly_runs?.length || ml.anomalies?.length ? (
                <ul className="attention">
                  {(ml.anomaly_runs ?? []).slice(0, 4).map((run, i) => (
                    <li key={`r${i}`}><Pill status="warning">Alert run</Pill><div><b>{run.device_id}</b><small>{formatUtc(run.start_utc)} → {formatUtc(run.end_utc)} · {run.intervals} intervals</small></div></li>
                  ))}
                  {(ml.hypotheses ?? []).slice(0, 3).map((h, i) => (
                    <li key={`h${i}`}><Pill status={h.status === "confirmed_event" ? "success" : "suspected"}>{h.status === "confirmed_event" ? "Event logged" : "Unconfirmed"}</Pill><div><b>{h.label}</b><small>{h.interval?.device_id ?? "Plant"} · {formatUtc(h.interval?.timestamp_utc)}</small></div></li>
                  ))}
                </ul>
              ) : <Empty icon="check" title="Nothing flagged" body="The ML service raised no alerts or hypotheses for this dataset." />}
              <Link className="text-link" style={{ marginTop: 12 }} to={`${base}/assistant?report=${detail.request_id}`}>Ask about this report <Icon name="arrow-right" /></Link>
            </Card>
          </div>
          <div className="ws-grid-2">
            <Card title="Data quality" icon="shield-check" actions={<Pill status={ml.data_quality?.status} />}>
              <QualityBar dq={ml.data_quality} />
              <Link className="text-link" style={{ marginTop: 14 }} to={`${base}/validation?report=${detail.request_id}`}>Open Validation Lab <Icon name="arrow-right" /></Link>
            </Card>
            <Card title="Recent reports" icon="report" actions={<Link className="text-link" to={`${base}/reports`}>All reports</Link>}>
              <div className="report-list">{scoped.slice(0, 4).map((item) => <ReportRow key={item.request_id} base={base} item={item} plantName={plantName(item.plant_id)} />)}</div>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
