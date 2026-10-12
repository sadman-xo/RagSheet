import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { downloadGet, errorMessage, get } from "@/api/client";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";

interface AuditRow {
  id: number;
  ts: string;
  username: string | null;
  role: string | null;
  action: string;
  scope_key: string | null;
  ip: string | null;
  replica: string | null;
  detail: Record<string, unknown>;
  flags: string[];
}
interface AuditPage {
  rows: AuditRow[];
  next_before_id: number | null;
  summary_24h: { action: string; n: number }[];
}

const TONE: Record<string, "red" | "amber" | "green" | "blue" | "slate"> = {
  scope_violation: "red", scope_mismatch: "red", permission_denied: "red", login_failed: "amber", login_locked: "red",
  login: "green", logout: "slate", export: "blue", user_change: "amber", chat_query: "blue", leak_scan: "red",
};

export default function AuditTab() {
  const [action, setAction] = useState("");
  const [username, setUsername] = useState("");
  const params = new URLSearchParams();
  if (action) params.set("action", action);
  if (username) params.set("username", username);
  const q = useInfiniteQuery<AuditPage>({
    queryKey: ["audit", action, username],
    queryFn: ({ pageParam }) => get<AuditPage>(`/admin/audit?limit=100&${params.toString()}${pageParam ? `&before_id=${pageParam}` : ""}`),
    initialPageParam: null as number | null,
    getNextPageParam: (p) => p.next_before_id,
  });
  const rows = q.data?.pages.flatMap((p) => p.rows) ?? [];
  const summary = q.data?.pages[0]?.summary_24h ?? [];
  return (
    <div className="space-y-4">
      <Card title="Last 24 hours">
        <div className="flex flex-wrap gap-2">
          {summary.map((s) => (
            <button key={s.action} type="button" onClick={() => setAction(s.action === action ? "" : s.action)}>
              <Badge tone={TONE[s.action] ?? "slate"} className={action === s.action ? "ring-2 ring-brand-300" : ""}>{s.action}: {s.n}</Badge>
            </button>
          ))}
        </div>
      </Card>
      <Card
        title="Audit log"
        actions={
          <>
            <input className="input w-40 py-1 text-xs" placeholder="username" value={username} onChange={(e) => setUsername(e.target.value.trim())} />
            <input className="input w-40 py-1 text-xs" placeholder="action" value={action} onChange={(e) => setAction(e.target.value.trim())} />
            <button className="btn" onClick={() => downloadGet(`/admin/audit/export?${params.toString()}`, "panorama_audit.csv").catch((e) => alert(errorMessage(e)))}>
              <Download className="h-4 w-4" /> CSV
            </button>
          </>
        }
      >
        {q.isLoading ? <Loading /> : q.error ? <ErrorState message={errorMessage(q.error)} /> : (
          <div className="scrollbar-thin max-h-[560px] overflow-auto">
            <table className="w-full text-sm" data-testid="audit-table">
              <thead>
                <tr>{["Time", "User", "Action", "Scope", "Detail", "IP / replica"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 align-top">
                    <td className="table-cell text-xs text-slate-500">{new Date(r.ts).toLocaleString()}</td>
                    <td className="table-cell">{r.username ?? "–"}<div className="text-xs text-slate-400">{r.role}</div></td>
                    <td className="table-cell"><Badge tone={TONE[r.action] ?? "slate"}>{r.action}</Badge>{r.flags.map((f) => <Badge key={f} tone="red" className="ml-1">{f}</Badge>)}</td>
                    <td className="table-cell text-xs">{r.scope_key ?? "–"}</td>
                    <td className="max-w-md px-3 py-1.5"><code className="block max-h-16 overflow-hidden whitespace-pre-wrap break-all text-[11px] text-slate-600">{JSON.stringify(r.detail)}</code></td>
                    <td className="table-cell text-xs text-slate-500">{r.ip ?? "–"}<div>{r.replica}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {q.hasNextPage && (
              <button className="btn m-3" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>{q.isFetchingNextPage ? "Loading…" : "Load more"}</button>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
