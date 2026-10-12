import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import {
  AlertTriangle, ArrowRight, ArrowUp, Bot, Check, ClipboardCopy, ExternalLink, Info, ListTree, Loader2, ShieldCheck, Square, ThumbsDown, ThumbsUp,
} from "lucide-react";
import { get, post } from "@/api/client";
import type { QueryResult } from "@/api/types";
import { Chart } from "@/components/Chart";
import { ResultTable } from "@/components/DataTable";
import { Badge } from "@/components/ui";
import { autoChart } from "@/pages/Explorer";
import { useChatStatus } from "@/layout/AppShell";
import { cn } from "@/lib/cn";
import { LogoMark } from "@/components/Logo";
import type { ChatMessage, ChatResult } from "./useChat";
import { useChat } from "./useChat";

const STAGES: Record<string, string> = {
  sending: "Sending",
  understanding: "Reading the question",
  planning: "Planning the query",
  queued: "Waiting for the AI",
  retrieving: "Finding context",
  writing: "Writing the answer",
};

const MODE_BADGE: Record<string, { label: string; tone: "green" | "blue" | "amber" | "red" | "slate" | "violet"; tip: string }> = {
  ai: { label: "AI answer · verified", tone: "green", tip: "Every number in the text agrees with the results." },
  ai_replaced: { label: "Exact answer", tone: "amber", tip: "The AI text had a number that did not agree with the data. Panorama replaced it with the exact answer." },
  template: { label: "Exact answer", tone: "blue", tip: "A fixed text with the exact numbers. No AI was necessary." },
  cache: { label: "AI answer · cached", tone: "green", tip: "The same question with the same data was answered before." },
  refusal: { label: "Outside your access", tone: "red", tip: "The question asks for data that your role cannot see." },
  basic_shed: { label: "AI busy · direct result", tone: "amber", tip: "The AI queue was full. You get the exact result at once." },
  basic_down: { label: "AI not available · direct result", tone: "amber", tip: "The AI is not available now. You get the exact result." },
  cancelled: { label: "Stopped", tone: "slate", tip: "You stopped this answer." },
};

function withCitations(text: string): string {
  return text.replace(/\[([RS]\d{1,2})\]/g, "[$1](#cite-$1)");
}

function MiniResult({ r }: { r: ChatResult }) {
  const nav = useNavigate();
  const option = useMemo(() => (r.kind === "table" && r.rows.length > 1 ? autoChart({ ...(r as unknown as QueryResult), spec: r.spec ?? { metrics: [] } }) : null), [r]);
  if (r.kind === "definition" && r.definition) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-[13px]">
        <div className="font-semibold">{r.definition.label}</div>
        <div className="text-slate-600">{r.definition.description}</div>
        <div className="mt-1 font-mono text-xs text-slate-500">{r.definition.formula}</div>
      </div>
    );
  }
  if (r.kind === "notes" || r.kind === "access" || !r.columns?.length) return null;
  return (
    <div className="rounded-md border border-slate-200 bg-white" data-testid="chat-result">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/60 px-3 py-1.5">
        <span className="truncate text-xs font-semibold text-slate-700"><Badge tone="blue" className="mr-1">{r.ref}</Badge>{r.title}{r.compare ? ` · ${r.compare}` : ""}</span>
        {r.explorer_link && (
          <button type="button" className="btn-ghost shrink-0 text-xs" onClick={() => nav(r.explorer_link!)}>
            <ExternalLink className="h-3 w-3" /> Explorer
          </button>
        )}
      </div>
      {option && <div className="px-2 pt-2"><Chart option={option} height={170} /></div>}
      <div className="p-2">
        <ResultTable columns={r.columns} rows={r.rows} totals={r.rows.length > 1 ? r.totals : null} maxHeight={220} compact />
      </div>
      {r.notes?.length ? <p className="px-3 pb-2 text-[11px] text-amber-700">{r.notes[0]}</p> : null}
    </div>
  );
}

function Stage({ m }: { m: ChatMessage }) {
  if (m.done || !m.stage) return null;
  const order = ["understanding", "planning", "queued", "retrieving", "writing"];
  const label = m.stage === "queued" && m.queue ? `Queued #${m.queue.position} · ~${Math.round(m.queue.eta_s)} s` : STAGES[m.stage] ?? m.stage;
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500" data-testid="chat-stage">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      <span className="font-medium text-slate-700">{label}</span>
      <span className="flex gap-1">
        {order.map((s) => <span key={s} className={cn("h-1 w-4 rounded-full", order.indexOf(s) <= order.indexOf(m.stage!) ? "bg-slate-800" : "bg-slate-200")} />)}
      </span>
    </div>
  );
}

function AssistantMessage({ m, onExplain, onRate, busy }: { m: ChatMessage; onExplain: (qid: number) => void; onRate: (rating: number) => void; busy: boolean }) {
  const nav = useNavigate();
  const [copied, setCopied] = useState(false);
  const badge = m.mode ? MODE_BADGE[m.mode] : undefined;
  const linkOf = (ref: string) => (ref.startsWith("R") ? m.results.find((r) => r.ref === ref)?.explorer_link : m.sources.find((s) => s.ref === ref)?.deep_link);
  const firstLink = m.results.find((r) => r.explorer_link)?.explorer_link;
  return (
    <div className="space-y-2" data-testid="chat-answer">
      {m.plan && m.plan.summary && (
        <button type="button" className="chip max-w-full border-slate-200 bg-white font-normal text-slate-600 hover:border-slate-400" title="The plan that the assistant ran" onClick={() => firstLink && nav(firstLink)}>
          <ListTree className="h-3 w-3 shrink-0 text-slate-400" /> <span className="truncate">{m.plan.summary}</span>
          {firstLink && <span className="ml-1 shrink-0 font-medium text-brand-700">Open in Explorer</span>}
        </button>
      )}
      {m.notices.map((n) => (
        <div key={n.text} className={cn("flex items-start gap-1.5 rounded-md border px-2.5 py-1.5 text-xs", n.kind ? "border-amber-200 bg-amber-50/60 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-600")} data-testid="chat-notice">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {n.text}
        </div>
      ))}
      {m.results.map((r) => <MiniResult key={r.ref} r={r} />)}
      <Stage m={m} />
      {m.text && (
        <div className="max-w-none text-[13.5px] leading-relaxed text-slate-800 [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_strong]:font-semibold [&_strong]:text-slate-900 [&_ul]:list-disc [&_ul]:pl-5">
          <ReactMarkdown
            rehypePlugins={[rehypeSanitize]}
            components={{
              a: ({ href, children }) => {
                const ref = href?.startsWith("#cite-") ? href.slice(6) : null;
                if (ref) {
                  const link = linkOf(ref);
                  return (
                    <button type="button" onClick={() => link && nav(link)} title={link ? "Open the source" : undefined}
                      className={cn("mx-0.5 inline-flex items-center rounded-full px-1.5 py-0 align-baseline text-[10px] font-semibold", ref.startsWith("R") ? "bg-brand-100 text-brand-800" : "bg-slate-200 text-slate-800")}>
                      {ref}
                    </button>
                  );
                }
                return <a href={href} className="text-brand-700 underline">{children as ReactNode}</a>;
              },
            }}
          >
            {withCitations(m.text)}
          </ReactMarkdown>
        </div>
      )}
      {m.error && <div className="flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50/60 px-2.5 py-1.5 text-xs text-red-800"><AlertTriangle className="h-3.5 w-3.5" /> {m.error}</div>}
      {m.sources.length > 0 && (
        <div className="flex flex-wrap gap-1 text-[11px] text-slate-500" data-testid="chat-sources">
          <span className="font-medium">Sources:</span>
          {m.sources.map((s) => (
            <button key={s.ref} type="button" className="rounded border border-slate-200 px-1.5 hover:border-slate-400 hover:text-slate-800" onClick={() => s.deep_link && nav(s.deep_link)}>
              {s.ref} {s.title}
            </button>
          ))}
        </div>
      )}
      {m.done && !m.error && (
        <div className="flex flex-wrap items-center gap-1.5">
          {badge && <Badge tone={badge.tone} title={badge.tip}>{m.mode === "ai" ? <ShieldCheck className="h-3 w-3" /> : null}{badge.label}</Badge>}
          {(m.mode === "template" || m.mode === "basic_shed" || m.mode === "basic_down" || m.mode === "ai_replaced") && m.questionId && m.results.length > 0 && (
            <button type="button" className="btn-ghost text-xs" disabled={busy} onClick={() => onExplain(m.questionId!)} data-testid="chat-explain">
              <Bot className="h-3.5 w-3.5" /> Explain
            </button>
          )}
          <button type="button" className="btn-ghost text-xs" onClick={() => { navigator.clipboard?.writeText(m.text); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />}
          </button>
          {m.messageId ? (
            <>
              <button type="button" className={cn("btn-ghost", m.rating === 1 && "text-emerald-600")} aria-label="Good answer"
                onClick={() => post(`/chat/messages/${m.messageId}/feedback`, { rating: 1 }).then(() => onRate(1))}><ThumbsUp className="h-3.5 w-3.5" /></button>
              <button type="button" className={cn("btn-ghost", m.rating === -1 && "text-red-600")} aria-label="Bad answer"
                onClick={() => post(`/chat/messages/${m.messageId}/feedback`, { rating: -1 }).then(() => onRate(-1))}><ThumbsDown className="h-3.5 w-3.5" /></button>
            </>
          ) : null}
          {m.timings?.total ? <span className="text-[10px] text-slate-400">{(m.timings.total / 1000).toFixed(1)} s</span> : null}
        </div>
      )}
    </div>
  );
}

export function ChatView({ chat, compact, seed }: { chat: ReturnType<typeof useChat>; compact?: boolean; seed?: { text: string; nonce: number } | null }) {
  const [input, setInput] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const status = useChatStatus().data;
  const sugg = useQuery<{ suggestions: string[] }>({ queryKey: ["chat-suggestions"], queryFn: () => get("/chat/suggestions"), staleTime: Infinity });
  const lastSeed = useRef<number | null>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.messages]);

  useEffect(() => {
    if (seed && seed.nonce !== lastSeed.current && !chat.busy) {
      lastSeed.current = seed.nonce;
      chat.send(seed.text);
    }
  }, [seed, chat]);

  function submit() {
    const t = input.trim();
    if (!t || chat.busy) return;
    setInput("");
    chat.send(t);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-y-auto p-4" data-testid="chat-messages">
        {chat.messages.length === 0 && (
          <div className="mx-auto max-w-xl py-6 text-center">
            <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-slate-900"><LogoMark className="h-5 w-5" /></div>
            <h3 className="text-base font-semibold text-slate-900">Ask about your data</h3>
            <p className="mx-auto mb-5 mt-1 max-w-md text-[13px] leading-relaxed text-slate-500">The assistant shows the exact result table first, then a short explanation with sources. It sees only the data of your role.</p>
            {status && status.state !== "ready" && <p className="mb-3 text-xs text-amber-700">{status.label}{status.progress != null ? ` (${Math.round(status.progress)}%)` : ""}. You still get exact answers.</p>}
            <div className={cn("grid gap-px overflow-hidden rounded-md border border-slate-200 bg-slate-200 text-left", compact ? "" : "sm:grid-cols-2 sm:[&>*:last-child:nth-child(odd)]:col-span-2")} data-testid="chat-suggestions">
              {(sugg.data?.suggestions ?? []).map((s) => (
                <button key={s} type="button" className="group flex items-center justify-between gap-3 bg-white px-3 py-2.5 text-left text-[13px] text-slate-700 hover:bg-slate-50 hover:text-slate-900" onClick={() => chat.send(s)}>
                  {s} <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-600" />
                </button>
              ))}
            </div>
          </div>
        )}
        {chat.messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-lg rounded-br-sm bg-slate-900 px-3.5 py-2 text-[13.5px] text-white" data-testid="chat-question">{m.text}</div>
            </div>
          ) : (
            <div key={m.id} className="flex gap-2">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded bg-slate-900"><LogoMark className="h-4 w-4" /></div>
              <div className="min-w-0 flex-1"><AssistantMessage m={m} busy={chat.busy} onExplain={(qid) => chat.send("Explain this result", { explainOf: qid })} onRate={(r) => chat.rate(m.id, r)} /></div>
            </div>
          ),
        )}
        <div ref={end} />
      </div>
      <div className="border-t border-slate-200 bg-white p-3">
        <div className="flex items-end gap-2 rounded-md border border-slate-300 bg-white p-1.5 focus-within:border-slate-700">
          <textarea
            className="min-h-[40px] w-full resize-none bg-transparent px-1.5 py-1 text-[13.5px] outline-none placeholder:text-slate-400"
            rows={compact ? 2 : 2}
            maxLength={500}
            placeholder="Ask a question, for example: revenue by country in 2023"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            data-testid="chat-input"
          />
          {chat.busy ? (
            <button type="button" className="btn" onClick={chat.stop} data-testid="chat-stop"><Square className="h-4 w-4" /> Stop</button>
          ) : (
            <button type="button" className="btn-primary h-8 w-8 p-0" onClick={submit} disabled={!input.trim()} data-testid="chat-send" aria-label="Send"><ArrowUp className="h-4 w-4" /></button>
          )}
        </div>
        <p className="mt-1.5 text-[11px] text-slate-400">Answers use only your data scope. Numbers come from the data engine, not from the AI. {input.length}/500</p>
      </div>
    </div>
  );
}
