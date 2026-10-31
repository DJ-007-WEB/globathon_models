import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { useAnalysisDetail, useWorkspace } from "../../state/WorkspaceContext";
import { getChat } from "../../api/endpoints";
import { streamChat } from "../../api/chat";
import { FALLBACK_MODELS, type ChatMessage, type Explanation } from "../../types/backend";
import { formatKwh, formatUtc } from "../../lib/format";
import { Card, Empty, ErrorNote, ExplanationView, Loading, PageHead } from "../ui";

const SUGGESTIONS = [
  "Why did the plant deliver less than forecast?",
  "Which inverter needs attention first?",
  "How much of the gap is weather and how much is the plant?",
  "What should the site team check next?",
  "How reliable is this data?",
];

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part);
}
function Markdown({ source }: { source: string }) {
  return <>{source.split(/\r?\n/).map((line, i) => line.startsWith("### ") ? <h4 key={i}>{inline(line.slice(4))}</h4>
    : line.startsWith("- ") ? <div className="md-li" key={i}>• {inline(line.slice(2))}</div> : !line.trim() ? <div key={i} style={{ height: 6 }} /> : <p key={i}>{inline(line)}</p>)}</>;
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") return <div className="msg msg-user"><p>{message.content as string}</p></div>;
  const fallback = message.model ? FALLBACK_MODELS.has(message.model) : false;
  return (
    <div className="msg msg-ai">
      <span className="msg-tag">{fallback ? "Evidence-only fallback" : message.model ? `Local model · ${message.model}` : "Assistant"}</span>
      {typeof message.content === "string" ? <Markdown source={message.content} /> : <ExplanationView ex={message.content as Explanation} compact />}
    </div>
  );
}

export function Assistant() {
  const { base, mode, analyses, analysesLoading, selectedPlantId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const scoped = useMemo(() => analyses.filter((a) => !selectedPlantId || a.plant_id === selectedPlantId), [analyses, selectedPlantId]);
  const reportId = params.get("report") || scoped[0]?.request_id || analyses[0]?.request_id;
  const { detail, loading, error } = useAnalysisDetail(reportId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatError, setChatError] = useState("");
  const [question, setQuestion] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]); setChatError("");
    if (!reportId || mode === "preview") return;
    let active = true;
    getChat(reportId).then((r) => { if (active) setMessages(r.messages); }).catch((e) => { if (active) setChatError(e instanceof Error ? e.message : "Chat history could not be loaded."); });
    return () => { active = false; };
  }, [reportId, mode]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages, streaming]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || !reportId || busy) return;
    setQuestion(""); setChatError(""); setBusy(true); setStreaming("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    try {
      const { answer, model } = await streamChat(reportId, q, (t) => setStreaming(t));
      setMessages((m) => [...m, { role: "assistant", content: answer, model }]);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "The question could not be answered.");
    } finally { setStreaming(null); setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(question); };

  if (analysesLoading) return <Loading />;
  if (!analyses.length) return (<><PageHead eyebrow="AI Explanation" title="AI Explanation" />
    <Card><Empty icon="message" title="No reports to discuss" body="Upload an export first; the assistant answers questions about a saved report." action={mode === "live" ? <Link className="btn btn-royal" to={`${base}/upload`}>Upload data</Link> : undefined} /></Card></>);

  const ml = detail?.result.ml_analysis;
  return (
    <>
      <PageHead eyebrow="AI Explanation" title="Ask about a report" body="Answers are grounded in the saved ML result. The model explains figures; it never calculates new ones."
        actions={<select className="select" value={reportId} onChange={(e) => setParams({ report: e.target.value })} aria-label="Report">
          {analyses.map((a) => <option key={a.request_id} value={a.request_id}>{a.filename} · {formatUtc(a.created_at)}</option>)}</select>} />
      {loading && <Loading rows={2} />}
      {error && <ErrorNote message={error} />}
      {detail && (
        <div className="assistant-grid">
          <div className="assistant-side">
            <Card title="ML summary" icon="database">
              {ml ? <>
                <p className="muted" style={{ fontSize: 14 }}>{ml.summary}</p>
                <dl className="dl">
                  <dt>Actual</dt><dd>{formatKwh(ml.energy?.actual?.value_kwh)}</dd>
                  <dt>Expected</dt><dd>{formatKwh(ml.energy?.expected?.value_kwh)}</dd>
                  <dt>Weather effect</dt><dd>{formatKwh(ml.waterfall?.weather_effect_kwh)}</dd>
                  <dt>Plant effect</dt><dd>{formatKwh(ml.waterfall?.plant_effect_kwh)}</dd>
                  <dt>Anomalies</dt><dd>{ml.anomalies?.length ?? 0}</dd>
                  <dt>Hypotheses</dt><dd>{ml.hypotheses?.length ?? 0}</dd>
                </dl>
              </> : <p className="muted">No ML result.</p>}
              <Link className="text-link" to={`${base}/reports/${detail.request_id}`}>Open full report <Icon name="arrow-right" /></Link>
            </Card>
            <Card title="Report explanation" icon="sparkle">
              {detail.result.analysis ? <ExplanationView ex={detail.result.analysis} compact /> : <p className="muted">{mode === "preview" ? "Synthetic preview reports have no AI narrative." : "No explanation was saved."}</p>}
            </Card>
          </div>
          <Card className="chat-card" title="Conversation" icon="message">
            {mode === "preview" ? <Empty icon="message" title="Chat is disabled in the synthetic preview" body="Create a workspace to ask the local model about your own reports." action={<Link className="btn btn-royal" to="/app">Open your workspace</Link>} /> : <>
              <div className="chat-log" aria-live="polite">
                {!messages.length && streaming === null && <p className="muted chat-empty">Ask a question about this report, or pick a suggestion below.</p>}
                {messages.map((m, i) => <Message key={i} message={m} />)}
                {streaming !== null && <div className="msg msg-ai"><span className="msg-tag">Generating…</span>{streaming ? <Markdown source={streaming} /> : <span className="typing"><i /><i /><i /></span>}</div>}
                <div ref={endRef} />
              </div>
              {chatError && <ErrorNote message={chatError} />}
              <div className="suggestions">{SUGGESTIONS.map((s) => <button key={s} type="button" className="chip" disabled={busy} onClick={() => void ask(s)}>{s}</button>)}</div>
              <form className="composer" onSubmit={submit}>
                <textarea rows={2} placeholder="Ask about this report…" value={question} onChange={(e) => setQuestion(e.target.value)} disabled={busy}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(question); } }} aria-label="Question" />
                <button type="submit" className="btn btn-royal" disabled={busy || !question.trim()} aria-label="Send">{busy ? <span className="spinner" /> : <Icon name="send" />}</button>
              </form>
            </>}
          </Card>
        </div>
      )}
    </>
  );
}
