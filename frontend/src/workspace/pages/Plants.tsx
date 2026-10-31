import { useMemo, useState, type FormEvent } from "react";
import { useWorkspace } from "../../state/WorkspaceContext";
import { createPlant } from "../../api/endpoints";
import { formatNumber } from "../../lib/format";
import { Icon } from "../../design/Icon";
import { Card, Empty, ErrorNote, Loading, PageHead, ReportRow } from "../ui";

export function Plants() {
  const { base, mode, plants, plantsLoading, plantsError, refreshPlants, selectedPlantId, selectPlant, analyses } = useWorkspace();
  const [form, setForm] = useState({ plant_id: "", name: "", location: "", capacity_kw: "", timezone: "" });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = plants.find((p) => p.plant_id === selectedPlantId);
  const history = useMemo(() => analyses.filter((a) => a.plant_id === selectedPlantId), [analyses, selectedPlantId]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault(); setError("");
    const id = form.plant_id.trim() || form.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const capacity = form.capacity_kw.trim() ? Number(form.capacity_kw) : null;
    if (capacity !== null && !(capacity > 0)) { setError("Capacity must be a positive number of kW."); return; }
    setBusy(true);
    try {
      const plant = await createPlant({ plant_id: id, name: form.name.trim(), location: form.location.trim() || null, capacity_kw: capacity, timezone: form.timezone.trim() || null });
      await refreshPlants(); selectPlant(plant.plant_id);
      setForm({ plant_id: "", name: "", location: "", capacity_kw: "", timezone: "" }); setOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : "The plant could not be registered."); }
    finally { setBusy(false); }
  }

  return (
    <>
      <PageHead eyebrow="Plant data" title="Plants" body="Each plant keeps its own report history."
        actions={mode === "live" && <button type="button" className="btn btn-royal" onClick={() => setOpen((v) => !v)}><Icon name={open ? "x" : "plus"} />{open ? "Close" : "Register plant"}</button>} />
      {plantsError && <ErrorNote message={plantsError} onRetry={() => void refreshPlants()} />}
      {open && mode === "live" && (
        <Card title="Register a plant" icon="plant">
          <form className="form form-grid" onSubmit={submit}>
            <label>Name<input required value={form.name} onChange={set("name")} placeholder="e.g. Gurugram rooftop" /></label>
            <label>Plant ID <small className="muted">optional</small><input value={form.plant_id} onChange={set("plant_id")} placeholder="Derived from the name" pattern="[A-Za-z0-9_.\-]+" /></label>
            <label>Location <small className="muted">optional</small><input value={form.location} onChange={set("location")} /></label>
            <label>Capacity (kW) <small className="muted">optional</small><input inputMode="decimal" value={form.capacity_kw} onChange={set("capacity_kw")} /></label>
            <label>Timezone <small className="muted">optional</small><input value={form.timezone} onChange={set("timezone")} placeholder="e.g. Asia/Kolkata" /></label>
            <div className="form-actions">{error && <p className="form-error" role="alert">{error}</p>}<button type="submit" className="btn btn-royal" disabled={busy}>{busy && <span className="spinner" />}Register plant</button></div>
          </form>
        </Card>
      )}
      {plantsLoading ? <Loading /> : !plants.length ? (
        <Card><Empty icon="plant" title="No plants yet" body="Register a plant to start uploading exports." /></Card>
      ) : (
        <div className="ws-grid-2 wide-right">
          <Card title={`Plants (${plants.length})`} icon="plant">
            <ul className="plant-list">{plants.map((p) => (
              <li key={p.plant_id}><button type="button" className={p.plant_id === selectedPlantId ? "active" : ""} onClick={() => selectPlant(p.plant_id)}>
                <b>{p.name}</b><small className="muted">{p.plant_id}{p.location ? ` · ${p.location}` : ""}</small>
                <span className="count">{analyses.filter((a) => a.plant_id === p.plant_id).length}</span>
              </button></li>))}
            </ul>
          </Card>
          {selected && (
            <Card title={selected.name} icon="info">
              <dl className="dl">
                <dt>Plant ID</dt><dd><code>{selected.plant_id}</code></dd>
                <dt>Location</dt><dd>{selected.location || "—"}</dd>
                <dt>Capacity</dt><dd>{selected.capacity_kw != null ? `${formatNumber(selected.capacity_kw)} kW` : "—"}</dd>
                <dt>Timezone</dt><dd>{selected.timezone || "—"}</dd>
                <dt>Reports</dt><dd>{history.length}</dd>
              </dl>
              <h3 className="sub-h">Report history</h3>
              {history.length ? <div className="report-list">{history.map((item) => <ReportRow key={item.request_id} base={base} item={item} />)}</div>
                : <p className="muted">No reports for this plant yet.</p>}
            </Card>
          )}
        </div>
      )}
    </>
  );
}
