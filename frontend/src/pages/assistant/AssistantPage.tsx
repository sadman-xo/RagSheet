import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Plus } from "lucide-react";
import { get } from "@/api/client";
import { useUi } from "@/state/ui";
import { Card, PageHeader } from "@/components/ui";
import { cn } from "@/lib/cn";
import { ChatView } from "./ChatView";
import { useChat, type ChatMessage } from "./useChat";

interface SessionRow {
  id: number;
  title: string;
  updated_at: string;
  messages: number;
}

interface SessionDetail {
  id: number;
  title: string;
  stale: boolean;
  messages: { id: number; role: "user" | "assistant"; content: string; plan: { intent: string } | null; mode: string | null; rating: number | null; parent_message_id: number | null }[];
}

export default function AssistantPage() {
  const chat = useChat();
  const seed = useUi((s) => s.chatSeed);
  const sessions = useQuery<{ sessions: SessionRow[] }>({ queryKey: ["chat-sessions"], queryFn: () => get("/chat/sessions") });

  async function open(id: number) {
    const s = await get<SessionDetail>(`/chat/sessions/${id}`);
    const msgs: ChatMessage[] = s.messages.map((m) => ({
      id: `h-${m.id}`, role: m.role, text: m.content, notices: s.stale && m.role === "assistant" ? [{ text: "Your access changed since this answer." }] : [],
      results: [], sources: [], done: true, mode: m.mode ?? undefined, messageId: m.role === "assistant" ? m.id : undefined,
      questionId: m.role === "assistant" ? m.parent_message_id ?? undefined : m.id, rating: m.rating ?? undefined,
    }));
    const lastQ = [...s.messages].reverse().find((m) => m.role === "user")?.id ?? null;
    chat.load(s.stale ? null : s.id, msgs, s.stale ? null : lastQ);
  }

  return (
    <div className="flex h-full flex-col pt-4">
      <PageHeader title="Assistant" subtitle="Questions in plain English, answered from your data scope" />
      <div className="grid min-h-0 flex-1 gap-4 pb-2 lg:grid-cols-[260px_1fr]">
        <Card title="Conversations" actions={<button className="btn-ghost text-xs" onClick={chat.reset} data-testid="chat-new"><Plus className="h-3.5 w-3.5" /> New</button>} className="hidden lg:flex" bodyClass="p-2">
          <div className="scrollbar-thin max-h-[calc(100vh-260px)] space-y-1 overflow-y-auto">
            {(sessions.data?.sessions ?? []).map((s) => (
              <button key={s.id} type="button" onClick={() => open(s.id)}
                className={cn("flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-[13px] hover:bg-slate-100", chat.sessionId === s.id && "bg-slate-100")}>
                <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span className="min-w-0">
                  <span className="block truncate text-slate-800">{s.title}</span>
                  <span className="block text-[11px] text-slate-400">{new Date(s.updated_at).toLocaleString()} · {s.messages} messages</span>
                </span>
              </button>
            ))}
            {sessions.data?.sessions.length === 0 && <p className="px-2 text-xs text-slate-400">No conversations yet.</p>}
          </div>
        </Card>
        <div className="card flex h-[calc(100vh-190px)] min-h-[420px] flex-col overflow-hidden" data-testid="assistant-page">
          <ChatView chat={chat} seed={seed} />
        </div>
      </div>
    </div>
  );
}
