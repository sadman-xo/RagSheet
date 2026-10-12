import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, Lock, Sigma } from "lucide-react";
import { get } from "@/api/client";
import { useDataNotes } from "@/api/hooks";
import { useMe } from "@/auth/AuthProvider";
import { Badge, Card, Loading, PageHeader } from "@/components/ui";

interface ColumnInfo {
  name: string;
  label: string;
  kind: string;
  sensitivity: string;
  description: string;
  visible: boolean;
  note: string | null;
}

export default function DataNotes() {
  const me = useMe();
  const notes = useDataNotes();
  const cols = useQuery<{ columns: ColumnInfo[] }>({ queryKey: ["columns"], queryFn: () => get("/meta/columns"), staleTime: Infinity });
  return (
    <div className="pt-4">
      <PageHeader title="Data Notes" subtitle="What the numbers mean, how they are calculated, and the known data quality problems" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-600" /> Data quality notes</span>} subtitle="Evidence from your own data scope" className="xl:col-span-2" testId="data-quality">
          {notes.isLoading ? <Loading /> : (
            <div className="grid gap-3 md:grid-cols-2">
              {notes.data?.notes.map((n) => (
                <div key={n.id} className="rounded border border-slate-200 p-3">
                  <h4 className="text-sm font-semibold text-slate-800">{n.title}</h4>
                  <p className="mt-1 text-sm text-slate-600">{n.text}</p>
                  {n.evidence.length > 0 && (
                    <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
                      {n.evidence.map((e) => <li key={e}>{e}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title={<span className="flex items-center gap-2"><Sigma className="h-4 w-4 text-slate-400" /> Metric glossary</span>} subtitle="One registry for dashboards, exports, and the assistant">
          <div className="scrollbar-thin max-h-[520px] overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {me.metrics.map((m) => (
                  <tr key={m.id} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3 font-medium text-slate-800">{m.label}{m.financial && <Badge tone="violet" className="ml-1">financial</Badge>}</td>
                    <td className="py-2 text-slate-600">{m.description}<div className="font-mono text-[11px] text-slate-400">{m.formula}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-slate-400" /> Column dictionary</span>} subtitle="The columns of one order">
          <div className="scrollbar-thin max-h-[520px] overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {cols.data?.columns.map((c) => (
                  <tr key={c.name} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-800">{c.label}</div>
                      <div className="font-mono text-[11px] text-slate-400">{c.name}</div>
                    </td>
                    <td className="py-2 text-slate-600">
                      {c.description}
                      {c.note && (
                        <div className="mt-0.5 flex items-center gap-1 text-xs text-amber-700">
                          {!c.visible && <Lock className="h-3 w-3" />} {c.note}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Formulas" className="xl:col-span-2">
          <div className="grid gap-2 md:grid-cols-3">
            {notes.data?.formulas.map((f) => (
              <div key={f.name} className="rounded border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-medium text-slate-500">{f.name}</div>
                <div className="mt-1 font-mono text-sm text-slate-800">{f.formula}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
