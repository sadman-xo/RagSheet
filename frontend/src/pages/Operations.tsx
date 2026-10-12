import { useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { post } from "@/api/client";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { DistributionResponse, QuerySpec } from "@/api/types";
import { FilterBar } from "@/components/FilterBar";
import { barOption, boxplotOption } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { OrderDrawer } from "@/components/OrderDrawer";
import { Card, PageHeader, Segmented } from "@/components/ui";
import { KpiRow } from "@/dashboards/KpiRow";
import { num, pivot } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { SERIES, STATUS_COLORS } from "@/lib/colors";
import { count, pct } from "@/lib/format";

const STATUSES = ["Delivered", "Processing", "Returned", "Cancelled"];
const FULFILLED = ["Delivered", "Returned"];

export default function Operations() {
  const { filters, ready } = useApiFilters();
  const { drill } = useFilters();
  const [rateBy, setRateBy] = useState<"country" | "payment_method" | "shipping_method">("country");
  const [late, setLate] = useState(14);
  const [lookup, setLookup] = useState("");
  const [openOrder, setOpenOrder] = useState<string | null>(null);

  const fulfilled = useMemo(() => ({ ...filters, statuses: filters.statuses ?? FULFILLED }), [filters]);
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    statusMonth: { metrics: ["orders"], group_by: ["order_status"], time_grain: "year_month", filters, limit: 500, include_totals: false },
    method: { metrics: ["avg_shipping_cost", "avg_shipping_days", "orders"], group_by: ["shipping_method"], filters },
    rates: { metrics: ["return_rate", "cancellation_rate", "orders"], group_by: [rateBy], filters, limit: 100 },
    backlog: { metrics: ["open_orders"], time_grain: "year_month", filters, limit: 500, include_totals: true },
    days: { metrics: ["orders"], group_by: ["region", "shipping_days"], filters: fulfilled, limit: 500, include_totals: false },
  }), [filters, rateBy, fulfilled]);
  const b = useBatch(queries, ready);
  const r = b.data;

  const box = useQuery<DistributionResponse>({
    queryKey: ["dist", "shipping_days", "region", fulfilled],
    queryFn: () => post<DistributionResponse>("/analytics/distribution", { field: "shipping_days", group_by: "region", filters: fulfilled }),
    enabled: ready,
  });

  const statusOpt = useMemo(() => {
    const p = pivot(r?.statusMonth, "year_month", "order_status", "orders", STATUSES);
    return barOption(p.x, p.series.map((s) => ({ ...s, color: STATUS_COLORS[s.name] })), "count", { stack: true, legend: true });
  }, [r?.statusMonth]);

  const methodOpt = useMemo(() => {
    const rows = r?.method?.rows ?? [];
    return barOption(rows.map((x) => String(x.shipping_method)), [
      { name: "Avg shipping cost", data: rows.map((x) => num(x.avg_shipping_cost)), kind: "money" },
      { name: "Avg shipping days", data: rows.map((x) => num(x.avg_shipping_days)), type: "line", yAxis: 1, kind: "days", color: SERIES.aqua },
    ], "money", { kind2: "days", legend: true });
  }, [r?.method]);
  const methodNote = useMemo(() => {
    const rows = r?.method?.rows ?? [];
    const o = rows.find((x) => x.shipping_method === "Overnight");
    const e = rows.find((x) => x.shipping_method === "Economy");
    if (!o || !e || !num(e.avg_shipping_cost)) return null;
    return `Overnight costs about ${Math.round((num(o.avg_shipping_cost) ?? 0) / (num(e.avg_shipping_cost) ?? 1))}× Economy, but the shipping days are about the same (${(num(o.avg_shipping_days) ?? 0).toFixed(1)} vs ${(num(e.avg_shipping_days) ?? 0).toFixed(1)}). The region controls the delivery time.`;
  }, [r?.method]);

  const ratesOpt = useMemo(() => {
    const rows = r?.rates?.rows ?? [];
    return barOption(rows.map((x) => String(x[rateBy])), [
      { name: "Return rate", data: rows.map((x) => num(x.return_rate)), kind: "pct", color: SERIES.yellow },
      { name: "Cancellation rate", data: rows.map((x) => num(x.cancellation_rate)), kind: "pct", color: SERIES.red },
    ], "pct", { legend: true });
  }, [r?.rates, rateBy]);

  const backlogOpt = useMemo(() => {
    const rows = r?.backlog?.rows ?? [];
    return barOption(rows.map((x) => String(x.year_month)), [{ name: "Processing orders", data: rows.map((x) => num(x.open_orders)), kind: "count", color: SERIES.blue }], "count");
  }, [r?.backlog]);

  const lateStats = useMemo(() => {
    const rows = r?.days?.rows ?? [];
    const byRegion = new Map<string, { late: number; all: number }>();
    let lateAll = 0;
    let all = 0;
    for (const x of rows) {
      const n = num(x.orders) ?? 0;
      const d = num(x.shipping_days) ?? 0;
      const reg = String(x.region);
      const cur = byRegion.get(reg) ?? { late: 0, all: 0 };
      cur.all += n;
      all += n;
      if (d > late) {
        cur.late += n;
        lateAll += n;
      }
      byRegion.set(reg, cur);
    }
    return { rate: all ? (lateAll / all) * 100 : null, lateAll, all, regions: [...byRegion.entries()].map(([k, v]) => ({ region: k, rate: v.all ? (v.late / v.all) * 100 : 0, late: v.late })) };
  }, [r?.days, late]);

  const lateOpt = useMemo(() => barOption(lateStats.regions.map((x) => x.region), [{ name: `Late rate (> ${late} days)`, data: lateStats.regions.map((x) => x.rate), kind: "pct", color: SERIES.orange }], "pct"), [lateStats, late]);

  function submitLookup(e: FormEvent) {
    e.preventDefault();
    if (lookup.trim()) setOpenOrder(lookup.trim().toUpperCase());
  }

  return (
    <div>
      <FilterBar />
      <PageHeader
        title="Operations"
        subtitle="Fulfillment, shipping, returns, and cancellations"
        actions={
          <form onSubmit={submitLookup} className="flex items-center gap-2" data-testid="order-lookup">
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
              <input className="input w-48 pl-8" placeholder="Order ID (ORD-…)" value={lookup} onChange={(e) => setLookup(e.target.value)} />
            </div>
            <button className="btn">Look up</button>
          </form>
        }
      />
      <KpiRow metrics={["orders", "delivered_rate", "open_orders", "return_rate", "cancellation_rate", "avg_shipping_days", "avg_shipping_cost", "shipping_cost_total"]} />
      <div className="grid gap-4 lg:grid-cols-6">
        <Widget className="lg:col-span-4" title="Status mix by month" result={r?.statusMonth} loading={b.isFetching} error={b.error} option={statusOpt} />
        <Widget className="lg:col-span-2" title="Processing backlog by order month" subtitle={`${count(num(r?.backlog?.totals?.open_orders))} orders still Processing (a snapshot)`} result={r?.backlog} loading={b.isFetching} error={b.error} option={backlogOpt} />
        <Widget className="lg:col-span-3" title="Shipping days by region" subtitle="Delivered and returned orders (box plot)" loading={box.isFetching} error={box.error} option={box.data ? boxplotOption(box.data.groups, "days") : null} result={undefined} />
        <Widget className="lg:col-span-3" title="Cost vs days by shipping method" result={r?.method} loading={b.isFetching} error={b.error} option={methodOpt} footer={methodNote && <p className="text-xs text-slate-600">{methodNote}</p>} ask="Is faster shipping worth its cost?" />
        <Widget
          className="lg:col-span-3"
          title="Late deliveries"
          subtitle={`Share of fulfilled orders with more than ${late} shipping days: ${pct(lateStats.rate)}`}
          result={r?.days}
          loading={b.isFetching}
          error={b.error}
          option={lateOpt}
          onClick={(p) => p.name && drill("regions", p.name)}
          footer={
            <label className="flex items-center gap-3 text-xs text-slate-600">
              Late after
              <input type="range" min={3} max={24} value={late} onChange={(e) => setLate(Number(e.target.value))} className="w-48" data-testid="late-slider" />
              <span className="font-semibold">{late} days</span>
            </label>
          }
        />
        <Widget
          className="lg:col-span-3"
          title="Return and cancellation rates"
          result={r?.rates}
          loading={b.isFetching}
          error={b.error}
          option={ratesOpt}
          footer={<Segmented value={rateBy} onChange={setRateBy} options={[{ value: "country", label: "Country" }, { value: "payment_method", label: "Payment" }, { value: "shipping_method", label: "Shipping" }]} size="xs" />}
        />
        <Card className="lg:col-span-6" title="Rates table">
          {r?.rates && <ResultTable columns={r.rates.columns} rows={r.rates.rows} totals={r.rates.totals} maxHeight={260} compact />}
        </Card>
      </div>
      <OrderDrawer orderId={openOrder} onClose={() => setOpenOrder(null)} />
    </div>
  );
}
