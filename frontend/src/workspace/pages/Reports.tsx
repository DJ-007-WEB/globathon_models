import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useWorkspace } from "../../state/WorkspaceContext";
import { Card, Empty, ErrorNote, Loading, PageHead, ReportRow } from "../ui";

const STATUSES = ["all", "success", "partial", "invalid_input", "failed"];

export function Reports() {
  const { base, mode, analyses, analysesLoading, analysesError, refreshAnalyses, plants } = useWorkspace();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [plant, setPlant] = useState("all");
  const items = useMemo(() => analyses.filter((a) =>
    (status === "all" || a.analysis_status === status) && (plant === "all" || a.plant_id === plant) &&
    (!query || `${a.filename} ${a.request_id}`.toLowerCase().includes(query.toLowerCase()))), [analyses, status, plant, query]);
  const plantName = (id: string) => plants.find((p) => p.plant_id === id)?.name ?? id;
  return (
    <>
      <PageHead eyebrow="Reports" title="Saved reports" body={`${analyses.length} report${analyses.length === 1 ? "" : "s"} across ${plants.length} plant${plants.length === 1 ? "" : "s"}`}
        actions={mode === "live" && <Link className="btn btn-royal" to={`${base}/upload`}><Icon name="upload" />New analysis</Link>} />
      <div className="filters">
        <label className="search"><Icon name="search" size={16} /><input placeholder="Search by file name or ID" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search reports" /></label>
        <div className="chips" role="group" aria-label="Status">
          {STATUSES.map((s) => <button key={s} type="button" className={`chip ${status === s ? "active" : ""}`} aria-pressed={status === s} onClick={() => setStatus(s)}>{s === "all" ? "All" : s.replace("_", " ")}</button>)}
        </div>
        {plants.length > 1 && <select className="select" value={plant} onChange={(e) => setPlant(e.target.value)} aria-label="Plant"><option value="all">All plants</option>{plants.map((p) => <option key={p.plant_id} value={p.plant_id}>{p.name}</option>)}</select>}
      </div>
      {analysesError && <ErrorNote message={analysesError} onRetry={() => void refreshAnalyses()} />}
      {analysesLoading ? <Loading /> : (
        <Card>
          {items.length ? <div className="report-list">{items.map((item) => <ReportRow key={item.request_id} base={base} item={item} plantName={plantName(item.plant_id)} />)}</div>
            : <Empty icon="report" title={analyses.length ? "No reports match these filters" : "No reports yet"} body={analyses.length ? "Clear the search or choose another status." : "Upload an export to create your first report."} />}
        </Card>
      )}
    </>
  );
}
