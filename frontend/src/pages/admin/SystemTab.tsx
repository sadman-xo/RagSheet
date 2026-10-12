import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Database, HardDrive, Server } from "lucide-react";
import { errorMessage, get } from "@/api/client";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";
import { count, shortDate } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Sys = Record<string, any>;

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[160px_1fr] gap-x-3 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="font-medium text-slate-800">{v ?? "–"}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function SystemTab() {
  const q = useQuery<Sys>({ queryKey: ["admin-system"], queryFn: () => get("/admin/system"), refetchInterval: 5000 });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState message={errorMessage(q.error)} />;
  const s = q.data!;
  const gw = s.gateway ?? {};
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="system-page">
      <Card title={<span className="flex items-center gap-2"><Database className="h-4 w-4" /> Data</span>}>
        <Kv rows={[
          ["Dataset", s.dataset?.dataset],
          ["Orders", count(s.dataset?.row_count)],
          ["Date range", `${shortDate(s.dataset?.min_date)} – ${shortDate(s.dataset?.max_date)}`],
          ["Data version", <code key="dv">{s.dataset?.data_version}</code>],
          ["Loaded", s.dataset?.loaded_at ? new Date(s.dataset.loaded_at).toLocaleString() : "–"],
          ["RAG corpus", s.rag ? `${count(s.rag.doc_count)} documents (version ${s.rag.version})` : "not built"],
          ["Build", <code key="b">{s.build_id}</code>],
        ]} />
      </Card>
      <Card title={<span className="flex items-center gap-2"><Cpu className="h-4 w-4" /> LLM gateway</span>}>
        {gw.available === false ? <ErrorState message={`Gateway not reachable: ${gw.error ?? ""}`} className="min-h-0" /> : (
          <div className="space-y-3">
            <Kv rows={[
              ["State", <Badge key="st" tone={gw.state === "ready" ? "green" : "amber"}>{gw.state ?? "–"}</Badge>],
              ["Queue", `${gw.queue_length ?? 0} waiting · max ${gw.max_queue ?? "–"}`],
              ["In flight", `${gw.in_flight ?? 0} of ${gw.total_slots ?? "–"} slots`],
              ["Turn estimate (EWMA)", gw.ewma_s ? `${gw.ewma_s.toFixed(1)} s` : "–"],
              ["Turns (granted / shed / rejected)", `${gw.stats?.granted ?? 0} / ${gw.stats?.shed ?? 0} / ${gw.stats?.rejected ?? 0}`],
            ]} />
            <table className="w-full text-xs">
              <thead><tr>{["Endpoint", "Model", "Slots", "Breaker", "Model state", "VRAM", "tok/s"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
              <tbody>
                {(gw.endpoints ?? []).map((e: Sys) => (
                  <tr key={e.name} className="border-t border-slate-100">
                    <td className="table-cell">{e.name}<div className="text-slate-400">{e.provider}</div></td>
                    <td className="table-cell">{e.model}</td>
                    <td className="table-cell">{e.in_use}/{e.slots}</td>
                    <td className="table-cell"><Badge tone={e.breaker === "closed" ? "green" : "red"}>{e.breaker}</Badge></td>
                    <td className="table-cell">{e.model_state}{e.pull_progress != null && e.model_state === "downloading" ? ` ${Math.round(e.pull_progress)}%` : ""}</td>
                    <td className="table-cell">{e.vram_bytes ? `${(e.vram_bytes / 1e9).toFixed(2)} GB` : "–"}</td>
                    <td className="table-cell">{e.tokens_per_s ? e.tokens_per_s.toFixed(1) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title={<span className="flex items-center gap-2"><Server className="h-4 w-4" /> API replicas and processes</span>} subtitle={`This response from replica ${s.replica}. Audit rows dropped: ${s.audit_dropped_total}`}>
        <table className="w-full text-xs" data-testid="replicas-table">
          <thead><tr>{["Process", "Requests", "Write p95", "Cache hit rate", "Audit written", "Updated"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
          <tbody>
            {(s.workers ?? []).map((w: Sys) => (
              <tr key={w.process_id} className="border-t border-slate-100">
                <td className="table-cell font-mono">{w.process_id}</td>
                <td className="table-cell">{count(w.requests)}</td>
                <td className="table-cell">{w.write_p95_ms ? `${w.write_p95_ms.toFixed(1)} ms` : "–"}</td>
                <td className="table-cell">{w.cache_hits + w.cache_misses ? `${((w.cache_hits / (w.cache_hits + w.cache_misses)) * 100).toFixed(0)}%` : "–"}</td>
                <td className="table-cell">{count(w.audit_written)}</td>
                <td className="table-cell">{new Date(w.updated_at).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title={<span className="flex items-center gap-2"><HardDrive className="h-4 w-4" /> Scope files</span>} subtitle="One read-only DuckDB file for each data scope">
        <table className="w-full text-xs">
          <thead><tr>{["Scope", "Rows", "Size", "Rollup rows (geo / product / customer / ops)"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
          <tbody>
            {(s.scope_files ?? []).map((f: Sys) => (
              <tr key={f.key} className="border-t border-slate-100">
                <td className="table-cell font-mono">{f.key}</td>
                <td className="table-cell">{count(f.rows)}</td>
                <td className="table-cell">{(f.bytes / 1e6).toFixed(1)} MB</td>
                <td className="table-cell">{[f.rollup_rows.r_geo, f.rollup_rows.r_product, f.rollup_rows.r_customer, f.rollup_rows.r_ops].map((n: number) => count(n)).join(" / ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title={<span className="flex items-center gap-2"><Activity className="h-4 w-4" /> Database</span>} className="lg:col-span-2" subtitle={s.db_stats ? `${count(s.db_stats.xact_commit)} commits · ${s.db_stats.numbackends} connections` : undefined}>
        <div className="grid gap-4 lg:grid-cols-2">
          <table className="w-full text-xs">
            <thead><tr>{["User", "Application", "State", "Connections"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
            <tbody>
              {(s.db_connections ?? []).map((c: Sys, i: number) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="table-cell">{c.usename}</td><td className="table-cell">{c.application_name}</td><td className="table-cell">{c.state}</td><td className="table-cell">{c.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="w-full text-xs">
            <thead><tr>{["Slowest queries (mean)", "Calls", "Mean ms"].map((h) => <th key={h} className="table-head">{h}</th>)}</tr></thead>
            <tbody>
              {(s.slow_queries ?? []).map((sq: Sys, i: number) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="max-w-md truncate px-3 py-1 font-mono" title={sq.query}>{sq.query}</td><td className="table-cell">{count(sq.calls)}</td><td className="table-cell">{sq.mean_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
