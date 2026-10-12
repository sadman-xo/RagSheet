import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamChat, type ChatEvent } from "@/api/chat";
import { errorMessage } from "@/api/client";
import type { ColumnMeta, Row, QuerySpec } from "@/api/types";

export interface ChatResult {
  ref: string;
  kind: string;
  title: string;
  columns: ColumnMeta[];
  rows: Row[];
  row_count?: number;
  totals?: Row | null;
  compare?: string | null;
  source?: string;
  notes?: string[];
  explorer_link?: string | null;
  spec?: QuerySpec;
  definition?: { label: string; description: string; formula: string };
  notes_list?: { title: string; text: string; evidence: string[] }[];
  access?: Record<string, unknown>;
}

export interface ChatSource {
  ref: string;
  title: string;
  kind: string;
  deep_link: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  stage?: string;
  queue?: { position: number; eta_s: number } | null;
  plan?: { intent: string; summary: string; source: string } | null;
  notices: { text: string; kind?: string }[];
  results: ChatResult[];
  sources: ChatSource[];
  mode?: string;
  done: boolean;
  questionId?: number;
  messageId?: number;
  verification?: { ok?: boolean; checked?: number; unsupported?: unknown[] } | null;
  replaced?: string;
  error?: string;
  rating?: number;
  timings?: Record<string, number>;
}

export function useChat() {
  const qc = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const lastQuestion = useRef<number | null>(null);
  const abort = useRef<AbortController | null>(null);

  const patch = (id: string, f: (m: ChatMessage) => ChatMessage) => setMessages((ms) => ms.map((m) => (m.id === id ? f(m) : m)));

  const send = useCallback(async (text: string, opts: { explainOf?: number } = {}) => {
    if (busy || !text.trim()) return;
    const turnId = crypto.randomUUID();
    const aid = `a-${turnId}`;
    setMessages((ms) => [
      ...ms,
      { id: `u-${turnId}`, role: "user", text, notices: [], results: [], sources: [], done: true },
      { id: aid, role: "assistant", text: "", stage: "sending", notices: [], results: [], sources: [], done: false },
    ]);
    setBusy(true);
    const ctrl = new AbortController();
    abort.current = ctrl;
    const onEvent = (e: ChatEvent) => {
      const d = e.data as Record<string, unknown>;
      switch (e.event) {
        case "status":
          patch(aid, (m) => ({ ...m, stage: String(d.stage), queue: d.stage === "queued" ? { position: Number(d.queue_position), eta_s: Number(d.eta_s) } : null }));
          break;
        case "session":
          setSessionId(Number(d.session_id));
          break;
        case "plan":
          patch(aid, (m) => ({ ...m, plan: d as ChatMessage["plan"] }));
          break;
        case "notice":
          patch(aid, (m) => ({ ...m, notices: [...m.notices, { text: String(d.text), kind: d.kind as string | undefined }] }));
          break;
        case "data":
          patch(aid, (m) => ({ ...m, results: (d.results as ChatResult[]) ?? [], questionId: Number(d.question_id) }));
          break;
        case "sources":
          patch(aid, (m) => ({ ...m, sources: (d.sources as ChatSource[]) ?? [] }));
          break;
        case "token":
          patch(aid, (m) => ({ ...m, text: m.text + String(d.text), stage: "writing", queue: null }));
          break;
        case "replace":
          patch(aid, (m) => ({ ...m, text: String(d.text), replaced: String(d.reason ?? "") }));
          break;
        case "done":
          patch(aid, (m) => ({ ...m, done: true, mode: String(d.mode), messageId: Number(d.message_id), questionId: Number(d.question_id) || m.questionId,
            verification: (d.verification as ChatMessage["verification"]) ?? null, timings: d.timings as Record<string, number>, stage: undefined }));
          if (d.session_id) setSessionId(Number(d.session_id));
          if (d.question_id) lastQuestion.current = Number(d.question_id);
          break;
        case "error":
          patch(aid, (m) => ({ ...m, done: true, error: String(d.message ?? "The answer could not be completed."), stage: undefined }));
          break;
      }
    };
    try {
      await streamChat({ message: text, turn_id: turnId, parent_message_id: lastQuestion.current, session_id: sessionId,
        explain_of: opts.explainOf ?? null }, onEvent, ctrl.signal);
    } catch (err) {
      if (!ctrl.signal.aborted) patch(aid, (m) => ({ ...m, done: true, error: errorMessage(err), stage: undefined }));
    } finally {
      patch(aid, (m) => (m.done ? m : { ...m, done: true, stage: undefined, mode: ctrl.signal.aborted ? "cancelled" : m.mode }));
      setBusy(false);
      abort.current = null;
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    }
  }, [busy, sessionId, qc]);

  const stop = useCallback(() => abort.current?.abort(), []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setMessages([]);
    setSessionId(null);
    lastQuestion.current = null;
  }, []);

  const load = useCallback((sid: number | null, msgs: ChatMessage[], lastQ: number | null) => {
    abort.current?.abort();
    setMessages(msgs);
    setSessionId(sid);
    lastQuestion.current = lastQ;
  }, []);

  const rate = useCallback((id: string, rating: number) => patch(id, (m) => ({ ...m, rating })), []);

  return { messages, busy, send, stop, reset, load, sessionId, rate };
}
