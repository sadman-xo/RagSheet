import { useMemo } from "react";
import { Info } from "lucide-react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { FilterBar } from "@/components/FilterBar";
import { barOption, donutOption, heatmapOption } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { PageHeader } from "@/components/ui";
import { KpiRow } from "@/dashboards/KpiRow";
import { num } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { SERIES } from "@/lib/colors";

export default function Customers() {
  const me = useMe();
  const { filters, ready } = useApiFilters();
  const { revenueMetric } = useFilters();
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    segment: { metrics: [revenueMetric, "orders", "aov", "margin_pct"], group_by: ["customer_segment"], filters },
    gender: { metrics: [revenueMetric, "orders"], group_by: ["customer_gender"], filters },
    repeat: { metrics: ["unique_customers", "repeat_customer_rate"], group_by: ["customer_segment"], filters },
    heat: { metrics: [revenueMetric], group_by: ["customer_segment", "category"], filters, limit: 500, include_totals: false },
    top: { metrics: [revenueMetric, "orders", "aov"], group_by: ["customer_id"], filters, limit: 20 },
    pay: { metrics: ["orders", "cancellation_rate"], group_by: ["payment_method"], filters },
  }), [filters, revenueMetric]);
  const b = useBatch(queries, ready);
  const r = b.data;

  const segDonut = useMemo(() => donutOption((r?.segment?.rows ?? []).map((x) => ({ name: String(x.customer_segment), value: num(x[revenueMetric]) ?? 0 })), "money"), [r?.segment, revenueMetric]);
  const genDonut = useMemo(() => donutOption((r?.gender?.rows ?? []).map((x) => ({ name: String(x.customer_gender), value: num(x[revenueMetric]) ?? 0 })), "money"), [r?.gender, revenueMetric]);
  const repeat = useMemo(() => {
    const rows = r?.repeat?.rows ?? [];
    return barOption(rows.map((x) => String(x.customer_segment)), [
      { name: "Customers", data: rows.map((x) => num(x.unique_customers)), kind: "count", color: SERIES.blueLight },
      { name: "Repeat rate", data: rows.map((x) => num(x.repeat_customer_rate)), type: "line", yAxis: 1, kind: "pct", color: SERIES.aqua },
    ], "count", { kind2: "pct", legend: true });
  }, [r?.repeat]);
  const heat = useMemo(() => {
    const rows = r?.heat?.rows ?? [];
    const xs = [...new Set(rows.map((x) => String(x.category)))];
    const ys = ["New", "Regular", "Premium", "VIP"].filter((s) => rows.some((x) => x.customer_segment === s));
    return heatmapOption(xs, ys, rows.map((x) => [xs.indexOf(String(x.category)), ys.indexOf(String(x.customer_segment)), num(x[revenueMetric])]), "money");
  }, [r?.heat, revenueMetric]);
  const pay = useMemo(() => {
    const rows = r?.pay?.rows ?? [];
    return barOption(rows.map((x) => String(x.payment_method)), [
      { name: "Orders", data: rows.map((x) => num(x.orders)), kind: "count", color: SERIES.blueLight },
      { name: "Cancellation rate", data: rows.map((x) => num(x.cancellation_rate)), type: "line", yAxis: 1, kind: "pct", color: SERIES.red },
    ], "count", { kind2: "pct", legend: true });
  }, [r?.pay]);

  return (
    <div>
      <FilterBar />
      <PageHeader title="Customers" subtitle="Segments, repeat buying, and the top customers" />
      <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800" data-testid="attributes-banner">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        Segment, gender, and country are values at the time of each order. One customer can have different values on different orders.
        {me.scope.pii === "pseudonym" && " Customer IDs are pseudonyms (C-…) for your role."}
      </div>
      <KpiRow metrics={["unique_customers", "repeat_customer_rate", "orders", "aov"]} />
      <div className="grid gap-4 lg:grid-cols-6">
        <Widget className="lg:col-span-2" title="Revenue by segment" result={r?.segment} loading={b.isFetching} error={b.error} option={segDonut} height={240} />
        <Widget className="lg:col-span-2" title="Revenue by gender" result={r?.gender} loading={b.isFetching} error={b.error} option={genDonut} height={240} />
        <Widget className="lg:col-span-2" title="Customers and repeat rate by segment" result={r?.repeat} loading={b.isFetching} error={b.error} option={repeat} height={240} />
        <Widget className="lg:col-span-3" title="Segment × category" subtitle="Revenue" result={r?.heat} loading={b.isFetching} error={b.error} option={heat} height={260} />
        <Widget className="lg:col-span-3" title="Payment methods" result={r?.pay} loading={b.isFetching} error={b.error} option={pay} height={260} />
        <Widget className="lg:col-span-3" title="Segments" result={r?.segment} loading={b.isFetching} error={b.error}>
          {r?.segment && <ResultTable columns={r.segment.columns} rows={r.segment.rows} totals={r.segment.totals} compact />}
        </Widget>
        <Widget className="lg:col-span-3" title="Top 20 customers" subtitle={me.scope.pii === "pseudonym" ? "Pseudonyms" : undefined} result={r?.top} loading={b.isFetching} error={b.error}>
          {r?.top && <ResultTable columns={r.top.columns} rows={r.top.rows} maxHeight={320} compact />}
        </Widget>
      </div>
    </div>
  );
}
