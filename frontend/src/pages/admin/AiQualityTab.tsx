import { useQuery } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { errorMessage, get } from "@/api/client";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = Record<string, any>;

export default function AiQualityTab() {
  const q = useQuery<Any>({ queryKey: ["ai-quality"], queryFn: () => get("/admin/ai-quality?days=30") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState message={errorMessage(q.error)} />;
  const d = q.data!;
  const report = d.eval_report;
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="ai-quality-page">
      <Card title="Answers by mode (30 days)">
        <table className="w-full text-sm">
          <thead><tr>{["Mode", "Answers", "Thumbs up", "Thumbs down", "Avg time"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
          <tbody>
            {d.modes.map((m: Any) => (
              <tr key={m.mode} className="border-t border-slate-100">
                <td className="table-cell"><Badge>{m.mode}</Badge></td>
                <td className="table-cell">{m.answers}</td>
                <td className="table-cell text-emerald-700">{m.thumbs_up}</td>
                <td className="table-cell text-red-600">{m.thumbs_down}</td>
                <td className="table-cell">{m.avg_total_ms ? `${(m.avg_total_ms / 1000).toFixed(1)} s` : "–"}</td>
              </tr>
            ))}
            {!d.modes.length && <tr><td colSpan={5} className="p-4 text-center text-sm text-slate-400">No chat answers yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      <Card title="Latest evaluation report" subtitle={report ? `${report.model ?? ""} · ${report.created_at ?? ""}` : "Run scripts/run_eval.ps1"}>
        {report ? (
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap gap-2">
              {Object.entries(report.gates ?? {}).map(([k, v]: [string, any]) => (
                <Badge key={k} tone={v.pass ? "green" : "red"}>{k}: {typeof v.value === "number" ? v.value.toFixed(3) : String(v.value)} {v.pass ? "✓" : "✗"}</Badge>
              ))}
            </div>
            <pre className="max-h-72 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(report.summary ?? report, null, 2)}</pre>
          </div>
        ) : <p className="text-sm text-slate-400">No report yet.</p>}
      </Card>
      <Card title="Recent feedback" className="lg:col-span-2">
        <div className="space-y-2">
          {d.feedback.map((f: Any) => (
            <div key={`${f.message_id}`} className="rounded-md border border-slate-200 p-3 text-sm">
              <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
                {f.rating > 0 ? <ThumbsUp className="h-3.5 w-3.5 text-emerald-600" /> : <ThumbsDown className="h-3.5 w-3.5 text-red-600" />}
                {f.username} ({f.role}) · {new Date(f.created_at).toLocaleString()} · <Badge>{f.mode}</Badge>
              </div>
              <p className="font-medium">{f.question}</p>
              <p className="text-slate-600">{f.answer}</p>
              {f.comment && <p className="mt-1 italic text-slate-500">“{f.comment}”</p>}
            </div>
          ))}
          {!d.feedback.length && <p className="text-sm text-slate-400">No feedback yet.</p>}
        </div>
      </Card>
    </div>
  );
}
