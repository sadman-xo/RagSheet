import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bookmark, Bot, Copy, Download, Trash2 } from "lucide-react";
import { downloadPost, errorMessage, get } from "@/api/client";
import { useApiFilters, useQuerySpec } from "@/api/hooks";
import type { CompareMode, DimensionDef, MetricDef, QueryResult, QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { FilterBar } from "@/components/FilterBar";
import { barOption, heatmapOption, lineOption } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { Card, ErrorState, PageHeader } from "@/components/ui";
import { num, pivot, seriesOf } from "@/dashboards/helpers";
import { SourceNote, Widget } from "@/dashboards/Widget";
import { useUi } from "@/state/ui";
import { cn } from "@/lib/cn";

const GRAINS = [
  { id: "", label: "No time" },
  { id: "year", label: "Year" },
  { id: "year_quarter", label: "Quarter" },
  { id: "year_month", label: "Month" },
  { id: "week", label: "Week" },
  { id: "order_date", label: "Day" },
];

function useMeta() {
  return useQuery<{ metrics: MetricDef[]; dimensions: DimensionDef[] }>({ queryKey: ["meta-metrics"], queryFn: () => get("/meta/metrics"), staleTime: Infinity });
}

export function autoChart(res: QueryResult | undefined) {
  if (!res || !res.rows.length) return null;
  const dims = res.columns.filter((c) => c.role === "dim").map((c) => c.key);
  const metrics = res.columns.filter((c) => c.role === "metric");
  const m0 = metrics[0];
  const grain = res.spec.time_grain;
  if (grain && dims.length === 1) {
    const s = seriesOf(res, grain, metrics.slice(0, 2).map((m) => m.key));
    const twoKinds = metrics.length > 1 && metrics[1].kind !== m0.kind;
    return lineOption(s.x, s.series.map((x, i) => ({ ...x, yAxis: (twoKinds && i === 1 ? 1 : 0) as 0 | 1 })), m0.kind, { kind2: twoKinds ? metrics[1].kind : undefined, zoom: s.x.length > 30 });
  }
  if (grain && dims.length >= 2) {
    const p = pivot(res, grain, dims[1], m0.key);
    return lineOption(p.x, p.series.slice(0, 12), m0.kind, { zoom: p.x.length > 30 });
  }
  if (dims.length === 1) {
    const rows = res.rows.slice(0, 40);
    const twoKinds = metrics.length > 1 && metrics[1].kind !== m0.kind;
    return barOption(rows.map((r) => String(r[dims[0]])), metrics.slice(0, 2).map((m, i) => ({
      name: m.label, data: rows.map((r) => num(r[m.key])), kind: m.kind, ...(twoKinds && i === 1 ? { type: "line" as const, yAxis: 1 as const } : {}),
    })), m0.kind, { kind2: twoKinds ? metrics[1].kind : undefined, horizontal: rows.length > 12 && !twoKinds });
  }
  if (dims.length === 2) {
    const xs = [...new Set(res.rows.map((r) => String(r[dims[1]])))];
    const ys = [...new Set(res.rows.map((r) => String(r[dims[0]])))];
    return heatmapOption(xs, ys, res.rows.map((r) => [xs.indexOf(String(r[dims[1]])), ys.indexOf(String(r[dims[0]])), num(r[m0.key])]), m0.kind);
  }
  return null;
}

export default function Explorer() {
  const me = useMe();
  const meta = useMeta();
  const [sp, setSp] = useSearchParams();
  const { filters, ready } = useApiFilters();
  const { savedViews, saveView, deleteView, openChat } = useUi();
  const [copied, setCopied] = useState(false);

  const metrics = (sp.get("m") ?? "gross_revenue|orders").split("|").filter((m) => me.allowed_metrics.includes(m));
  const dims = (sp.get("g") ?? "region").split("|").filter(Boolean);
  const grain = sp.get("t") ?? "";
  const compare = (sp.get("cmp") ?? "none") as CompareMode;
  const limit = Number(sp.get("lim") ?? 100);
  const setParam = (k: string, v: string | null) => setSp((prev) => {
    const out = new URLSearchParams(prev);
    if (v) out.set(k, v);
    else out.delete(k);
    return out;
  });

  const spec = useMemo<QuerySpec | null>(() => {
    if (!ready || !metrics.length) return null;
    return { metrics, group_by: dims.filter((d) => d !== grain).slice(0, 2), time_grain: grain || null, filters, compare, limit };
  }, [ready, metrics.join("|"), dims.join("|"), grain, filters, compare, limit]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuerySpec(spec);
  const chart = useMemo(() => autoChart(q.data), [q.data]);

  const allowedMetrics = (meta.data?.metrics ?? me.metrics).filter((m) => me.allowed_metrics.includes(m.id));
  const dimOptions = (meta.data?.dimensions ?? []).filter((d) => !d.time_grain && (d.id !== "customer_id" || me.pages.includes("customers")));

  function toggleMetric(id: string) {
    const next = metrics.includes(id) ? metrics.filter((m) => m !== id) : [...metrics, id].slice(-6);
    setParam("m", next.join("|") || null);
  }

  return (
    <div>
      <FilterBar />
      <PageHeader
        title="Explorer"
        subtitle="Build your own view: metrics, up to two dimensions, a time grain, and filters"
        actions={
          <>
            <button className="btn" disabled={!spec} onClick={() => spec && downloadPost("/export/query", spec, "panorama_query.csv").catch((e) => alert(errorMessage(e)))}>
              <Download className="h-4 w-4" /> CSV
            </button>
            <button className="btn" onClick={() => { navigator.clipboard?.writeText(window.location.href); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              <Copy className="h-4 w-4" /> {copied ? "Copied" : "Copy link"}
            </button>
            <button className="btn" onClick={() => { const name = prompt("Name of the view?"); if (name) saveView({ name, path: "/explorer", search: window.location.search }); }}>
              <Bookmark className="h-4 w-4" /> Save view
            </button>
            <button className="btn" disabled={!q.data} onClick={() => openChat(`Explain this result: ${metrics.join(", ")} by ${[grain, ...dims].filter(Boolean).join(", ") || "total"}`)}>
              <Bot className="h-4 w-4" /> Ask AI
            </button>
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        <div className="space-y-4">
          <Card title="Metrics" subtitle="Up to 6">
            <div className="flex flex-wrap gap-1.5" data-testid="explorer-metrics">
              {allowedMetrics.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  title={m.description}
                  onClick={() => toggleMetric(m.id)}
                  className={cn("chip", metrics.includes(m.id) ? "border-brand-400 bg-brand-50 text-brand-800" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </Card>
          <Card title="Layout">
            <div className="space-y-3 text-sm">
              <label className="block">
                <span className="label">Time grain</span>
                <select className="input mt-1" value={grain} onChange={(e) => setParam("t", e.target.value || null)} data-testid="explorer-grain">
                  {GRAINS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
                </select>
              </label>
              {[0, 1].map((i) => (
                <label key={i} className="block">
                  <span className="label">Dimension {i + 1}</span>
                  <select
                    className="input mt-1"
                    value={dims[i] ?? ""}
                    data-testid={`explorer-dim-${i}`}
                    onChange={(e) => {
                      const next = [...dims];
                      next[i] = e.target.value;
                      setParam("g", next.filter(Boolean).slice(0, 2).join("|") || null);
                    }}
                  >
                    <option value="">None</option>
                    {dimOptions.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                  </select>
                </label>
              ))}
              <label className="block">
                <span className="label">Compare</span>
                <select className="input mt-1" value={compare} onChange={(e) => setParam("cmp", e.target.value === "none" ? null : e.target.value)}>
                  <option value="none">No comparison</option>
                  <option value="prior_year_lfl">Same period last year (like-for-like)</option>
                  <option value="prior_period">Prior period</option>
                </select>
              </label>
              <label className="block">
                <span className="label">Row limit</span>
                <select className="input mt-1" value={limit} onChange={(e) => setParam("lim", e.target.value)}>
                  {[10, 25, 100, 500].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            </div>
          </Card>
          {savedViews.length > 0 && (
            <Card title="Saved views" subtitle="In this browser">
              <ul className="space-y-1 text-sm">
                {savedViews.map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-2">
                    <button type="button" className="truncate text-left text-brand-700 hover:underline" onClick={() => setSp(new URLSearchParams(v.search))}>{v.name}</button>
                    <button type="button" className="btn-ghost" onClick={() => deleteView(v.id)} aria-label="Delete view"><Trash2 className="h-3.5 w-3.5" /></button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div className="min-w-0 space-y-4">
          {q.error ? (
            <ErrorState message={errorMessage(q.error)} />
          ) : (
            <>
              <Widget title="Chart" result={q.data} loading={q.isFetching} option={chart} height={360} footer={<SourceNote result={q.data} />} testId="explorer-chart" />
              <Card title="Pivot table" subtitle={q.data?.compare?.label}>
                {q.data && <ResultTable columns={q.data.columns} rows={q.data.rows} totals={q.data.totals} maxHeight={480} />}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
