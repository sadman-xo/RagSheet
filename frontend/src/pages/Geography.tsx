import { useMemo } from "react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { Chart } from "@/components/Chart";
import { FilterBar } from "@/components/FilterBar";
import { barOption, heatmapOption, sparkOption } from "@/components/charts";
import { Card, PageHeader } from "@/components/ui";
import { num } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { byKind, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { SERIES } from "@/lib/colors";

export default function Geography() {
  const me = useMe();
  const fin = me.scope.financial;
  const { filters, ready } = useApiFilters();
  const { revenueMetric, drill } = useFilters();
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    country: { metrics: [revenueMetric, "orders", fin ? "margin_pct" : "aov", "return_rate", "avg_shipping_days"], group_by: ["country"], filters, limit: 100 },
    spark: { metrics: [revenueMetric], group_by: ["country"], time_grain: "year_quarter", filters, limit: 500, include_totals: false },
    heat: { metrics: [revenueMetric], group_by: ["country", "category"], filters, limit: 500, include_totals: false },
    region: { metrics: [revenueMetric, "orders", fin ? "margin_pct" : "return_rate", "avg_shipping_days"], group_by: ["region"], filters },
  }), [filters, revenueMetric, fin]);
  const b = useBatch(queries, ready);
  const r = b.data;

  const sparks = useMemo(() => {
    const m = new Map<string, (number | null)[]>();
    const rows = [...(r?.spark?.rows ?? [])].sort((a, c) => String(a.year_quarter).localeCompare(String(c.year_quarter)));
    for (const x of rows) {
      const k = String(x.country);
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(num(x[revenueMetric]));
    }
    return m;
  }, [r?.spark, revenueMetric]);

  const heat = useMemo(() => {
    const rows = r?.heat?.rows ?? [];
    const xs = [...new Set(rows.map((x) => String(x.category)))];
    const ys = [...new Set(rows.map((x) => String(x.country)))];
    return heatmapOption(xs, ys, rows.map((x) => [xs.indexOf(String(x.category)), ys.indexOf(String(x.country)), num(x[revenueMetric])]), "money");
  }, [r?.heat, revenueMetric]);

  const shipOpt = useMemo(() => {
    const rows = [...(r?.country?.rows ?? [])].sort((a, c) => (num(c.avg_shipping_days) ?? 0) - (num(a.avg_shipping_days) ?? 0));
    return barOption(rows.map((x) => String(x.country)), [{ name: "Avg shipping days", data: rows.map((x) => num(x.avg_shipping_days)), kind: "days", color: SERIES.aqua }], "days", { horizontal: true });
  }, [r?.country]);

  const total = num(r?.country?.totals?.[revenueMetric]) ?? 0;
  const metricCol = fin ? "margin_pct" : "aov";

  return (
    <div>
      <FilterBar />
      <PageHeader title="Geography" subtitle="Regions and countries" />
      {me.scope.company_totals && (
        <div className="mb-4 grid gap-3 md:grid-cols-4" data-testid="region-cards">
          {(r?.region?.rows ?? []).map((x) => (
            <button key={String(x.region)} type="button" onClick={() => drill("regions", String(x.region))} className="card p-4 text-left transition hover:border-brand-300">
              <div className="label">{String(x.region)}</div>
              <div className="mt-1 text-xl font-semibold">{byKind("money", num(x[revenueMetric]), true)}</div>
              <div className="mt-1 text-xs text-slate-500">
                {byKind("count", num(x.orders))} orders · {fin ? `margin ${pct(num(x.margin_pct))}` : `returns ${pct(num(x.return_rate))}`} · {byKind("days", num(x.avg_shipping_days))}
              </div>
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-6">
        <Card className="lg:col-span-4" title="Country leaderboard" subtitle="Trend by quarter. Click a row to drill down.">
          <div className="scrollbar-thin max-h-[460px] overflow-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-head">Country</th>
                  <th className="table-head text-right">Revenue</th>
                  <th className="table-head text-right">Share</th>
                  <th className="table-head text-right">Orders</th>
                  <th className="table-head text-right">{fin ? "Margin" : "AOV"}</th>
                  <th className="table-head text-right">Return rate</th>
                  <th className="table-head w-36">Trend</th>
                </tr>
              </thead>
              <tbody>
                {(r?.country?.rows ?? []).map((x) => {
                  const n = num(x.return_rate__n);
                  return (
                    <tr key={String(x.country)} className="cursor-pointer border-t border-slate-100 hover:bg-brand-50/50" onClick={() => drill("countries", String(x.country))}>
                      <td className="table-cell font-medium">{String(x.country)}</td>
                      <td className="table-cell text-right tabular-nums">{byKind("money", num(x[revenueMetric]))}</td>
                      <td className="table-cell text-right tabular-nums text-slate-500">{total ? pct(((num(x[revenueMetric]) ?? 0) / total) * 100, 1) : "–"}</td>
                      <td className="table-cell text-right tabular-nums">{byKind("count", num(x.orders))}</td>
                      <td className="table-cell text-right tabular-nums">{byKind(fin ? "pct" : "money", num(x[metricCol]))}</td>
                      <td className={cn("table-cell text-right tabular-nums", n !== null && n < 30 && "text-slate-400")}>{pct(num(x.return_rate))}</td>
                      <td className="py-0"><Chart option={sparkOption(sparks.get(String(x.country)) ?? [], SERIES.blue)} height={28} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
        <Widget className="lg:col-span-2" title="Shipping days by country" subtitle="Delivered and returned orders" result={r?.country} loading={b.isFetching} error={b.error} option={shipOpt} height={460} />
        <Widget className="lg:col-span-6" title="Country × category" subtitle="Revenue" result={r?.heat} loading={b.isFetching} error={b.error} option={heat} height={Math.max(300, (r?.heat?.rows.length ?? 0) * 4 + 120)} />
      </div>
    </div>
  );
}
