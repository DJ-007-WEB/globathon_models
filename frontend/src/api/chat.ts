// Report-grounded follow-up chat: SSE stream with a non-streaming fallback for older backends.
import { getApiBase, getToken, messageFor, ApiError } from "./client";
import { askChat } from "./endpoints";
import type { Explanation } from "../types/backend";

export async function streamChat(requestId: string, question: string, onDelta: (text: string) => void): Promise<{ answer: Explanation; model?: string }> {
  const url = `${getApiBase()}/api/v1/analyses/${encodeURIComponent(requestId)}/chat/stream`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + getToken() },
      body: JSON.stringify({ question }),
      signal: AbortSignal.timeout(300000),
    });
  } catch {
    throw new ApiError(0, messageFor(0));
  }
  if (response.status === 404 || response.status === 405) {
    const data = await askChat(requestId, question);
    return { answer: data.answer, model: data.model };
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof body?.detail === "string" ? body.detail : messageFor(response.status));
  }
  if (!response.body) throw new ApiError(0, "This browser could not open the streaming response. Please retry.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamed = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() || "";
    for (const event of events) {
      const name = event.match(/^event:\s*(.+)$/m)?.[1]?.trim();
      const dataLine = event.split(/\r?\n/).find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const payload = JSON.parse(dataLine.slice(5).trim() || "{}");
      if (name === "delta" && typeof payload.text === "string") {
        streamed += payload.text;
        onDelta(streamed);
      } else if (name === "done" && payload.answer) {
        return { answer: payload.answer as Explanation, model: typeof payload.model === "string" ? payload.model : undefined };
      }
    }
  }
  throw new ApiError(0, "The response stream ended before the answer was complete. Please retry.");
}
