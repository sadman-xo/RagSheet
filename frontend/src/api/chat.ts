import { fetchEventSource } from "@microsoft/fetch-event-source";
import { ApiError } from "./client";

export interface ChatRequest {
  message: string;
  turn_id: string;
  parent_message_id?: number | null;
  explain_of?: number | null;
  session_id?: number | null;
}

export type ChatEvent = { event: string; data: Record<string, unknown> };

/** Options for the SSE client: no automatic retry (a retry would repeat a GPU turn), and the stream stays open
 * when the tab is hidden. */
export const SSE_OPTIONS = { openWhenHidden: true } as const;

export async function streamChat(req: ChatRequest, onEvent: (e: ChatEvent) => void, signal: AbortSignal): Promise<void> {
  await fetchEventSource("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(req),
    signal,
    ...SSE_OPTIONS,
    async onopen(res) {
      if (res.ok && res.headers.get("content-type")?.includes("text/event-stream")) return;
      let code = `HTTP_${res.status}`;
      let message = "The question could not be sent.";
      try {
        const body = await res.json();
        code = body?.error?.code ?? code;
        message = body?.error?.message ?? message;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, code, message, {}, Number(res.headers.get("Retry-After") ?? 0) || undefined);
    },
    onmessage(msg) {
      if (!msg.event) return;
      let data: Record<string, unknown> = {};
      try {
        data = msg.data ? JSON.parse(msg.data) : {};
      } catch {
        return;
      }
      onEvent({ event: msg.event, data });
    },
    onerror(err) {
      throw err; // never retry automatically
    },
  });
}
