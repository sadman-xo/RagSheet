import { useMemo } from "react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { Filters, QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { FilterBar } from "@/components/FilterBar";
import { barOption, donutOption, heatmapOption, lineOption, treemapOption, type TreeNode } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { PageHeader } from "@/components/ui";
import { InsightCards } from "@/dashboards/InsightCards";
import { KpiRow } from "@/dashboards/KpiRow";
import { num, pivot, seriesOf, toShares } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { SERIES, STATUS_COLORS } from "@/lib/colors";

const STATUSES = ["Delivered", "Processing", "Returned", "Cancelled"];

export default function Overview() {
  const me = useMe();
  const layout = me.user.role === "regional_manager" ? "region" : me.user.role === "category_manager" ? "category" : "company";
  const title = layout === "region" ? `Overview · ${me.user.region}` : layout === "category" ? `Overview · ${me.user.category}` : "Overview";
  return (
    <div>
      <FilterBar />
      <PageHeader title={title} subtitle={layout === "company" ? "Company performance at a glance" : `Your ${layout} at a glance (no company totals)`} />
      <KpiRow />
      {layout === "company" && <CompanyLayout />}
      {layout === "region" && <RegionLayout />}
      {layout === "category" && <CategoryLayout />}
      <div className="mt-4">
        <InsightCards />
      </div>
    </div>
  );
}

function usePeriodCompare(filters: Filters) {
  return filters.date_from || filters.date_to || filters.years ? "prior_year_lfl" : "none";
}

function CompanyLayout() {
  const me = useMe();
  const { filters, ready } = useApiFilters();
  const { revenueMetric, drill } = useFilters();
  const fin = me.scope.financial;
  const cmp = usePeriodCompare(filters);
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    monthly: { metrics: ["gross_revenue", "net_revenue"], time_grain: "year_month", filters, compare: cmp, limit: 500, include_totals: false },
    qy: { metrics: [revenueMetric], group_by: ["quarter"], time_grain: "year", filters, limit: 500, include_totals: false },
    region: { metrics: [revenueMetric, fin ? "margin_pct" : "return_rate"], group_by: ["region"], filters },
    tree: { metrics: [revenueMetric], group_by: ["category", "sub_category"], filters, limit: 100 },
    status: { metrics: ["orders"], group_by: ["order_status"], time_grain: "year", filters, limit: 500, include_totals: false },
    products: { metrics: [revenueMetric, "units", ...(fin ? ["margin_pct"] : ["return_rate"])], group_by: ["product"], filters, limit: 10 },
  }), [filters, revenueMetric, fin, cmp]);
  const b = useBatch(queries, ready);
  const r = b.data;
  const revLabel = revenueMetric === "net_revenue" ? "Net revenue" : "Gross revenue";

  const monthly = useMemo(() => {
    const s = seriesOf(r?.monthly, "year_month", ["gross_revenue", "net_revenue"], { gross_revenue: "Gross", net_revenue: "Net" });
    if (cmp !== "none" && r?.monthly) s.series.push({ name: "Gross, prior year", data: r.monthly.rows.map((x) => num(x.gross_revenue__prior)), dashed: true, color: SERIES.prior });
    return lineOption(s.x, s.series, "money", { zoom: s.x.length > 24 });
  }, [r?.monthly, cmp]);

  const qy = useMemo(() => {
    const p = pivot(r?.qy, "quarter", "year", revenueMetric);
    return barOption(p.x.map((q) => `Q${q}`), p.series, "money");
  }, [r?.qy, revenueMetric]);

  const region = useMemo(() => {
    const rows = r?.region?.rows ?? [];
    const m2 = fin ? "margin_pct" : "return_rate";
    return barOption(rows.map((x) => String(x.region)), [
      { name: revLabel, data: rows.map((x) => num(x[revenueMetric])), kind: "money" },
      { name: fin ? "Margin" : "Return rate", data: rows.map((x) => num(x[m2])), type: "line", yAxis: 1, kind: "pct", color: SERIES.orange },
    ], "money", { kind2: "pct", legend: true });
  }, [r?.region, fin, revenueMetric, revLabel]);

  const tree = useMemo(() => {
    const byCat = new Map<string, TreeNode>();
    for (const x of r?.tree?.rows ?? []) {
      const c = String(x.category);
      if (!byCat.has(c)) byCat.set(c, { name: c, value: 0, children: [] });
      const node = byCat.get(c)!;
      const v = num(x[revenueMetric]) ?? 0;
      node.value += v;
      node.children!.push({ name: String(x.sub_category), value: v });
    }
    return treemapOption([...byCat.values()], "money");
  }, [r?.tree, revenueMetric]);

  const status = useMemo(() => {
    const p = pivot(r?.status, "year", "order_status", "orders", STATUSES);
    return barOption(p.x, toShares(p.series).map((s) => ({ ...s, color: STATUS_COLORS[s.name] })), "pct", { stack: true, percent: true, legend: true });
  }, [r?.status]);

  return (
    <div className="grid gap-4 lg:grid-cols-6">
      <Widget className="lg:col-span-4" title="Monthly revenue" subtitle={cmp !== "none" ? "Gross, net, and gross of the prior year (like-for-like)" : "Gross and net revenue by month"} result={r?.monthly} loading={b.isFetching} error={b.error} option={monthly} ask="How did monthly revenue develop, and why?" testId="w-monthly" />
      <Widget className="lg:col-span-2" title="Quarter by year" subtitle={revLabel} result={r?.qy} loading={b.isFetching} error={b.error} option={qy} />
      <Widget className="lg:col-span-3" title={`Revenue by region${fin ? " with margin" : ""}`} result={r?.region} loading={b.isFetching} error={b.error} option={region} onClick={(p) => p.name && drill("regions", p.name)} subtitle="Click a region to drill down" testId="w-region" />
      <Widget className="lg:col-span-3" title="Category › sub-category" subtitle={revLabel} result={r?.tree} loading={b.isFetching} error={b.error} option={tree} height={300} />
      <Widget className="lg:col-span-3" title="Status mix by year" subtitle="Share of orders" result={r?.status} loading={b.isFetching} error={b.error} option={status} />
      <Widget className="lg:col-span-3" title="Top 10 products" result={r?.products} loading={b.isFetching} error={b.error}>
        {r?.products && <ResultTable columns={r.products.columns} rows={r.products.rows} maxHeight={300} compact />}
      </Widget>
    </div>
  );
}

function RegionLayout() {
  const me = useMe();
  const { filters, ready } = useApiFilters();
  const { revenueMetric, drill } = useFilters();
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    country: { metrics: [revenueMetric, "margin_pct"], group_by: ["country"], filters },
    countryMonth: { metrics: [revenueMetric], group_by: ["country"], time_grain: "year_month", filters, limit: 500, include_totals: false },
    catQuarter: { metrics: [revenueMetric], group_by: ["category"], time_grain: "year_quarter", filters, limit: 500, include_totals: false },
    products: { metrics: [revenueMetric, "units", "margin_pct"], group_by: ["product"], filters, limit: 10 },
    ops: { metrics: ["return_rate", "avg_shipping_days"], group_by: ["country"], filters },
  }), [filters, revenueMetric]);
  const b = useBatch(queries, ready);
  const r = b.data;
  const country = useMemo(() => {
    const rows = r?.country?.rows ?? [];
    return barOption(rows.map((x) => String(x.country)), [
      { name: "Revenue", data: rows.map((x) => num(x[revenueMetric])), kind: "money" },
      { name: "Margin", data: rows.map((x) => num(x.margin_pct)), type: "line", yAxis: 1, kind: "pct", color: SERIES.orange },
    ], "money", { kind2: "pct", legend: true });
  }, [r?.country, revenueMetric]);
  const lines = useMemo(() => {
    const p = pivot(r?.countryMonth, "year_month", "country", revenueMetric);
    return lineOption(p.x, p.series, "money", { zoom: p.x.length > 24 });
  }, [r?.countryMonth, revenueMetric]);
  const catQ = useMemo(() => {
    const p = pivot(r?.catQuarter, "year_quarter", "category", revenueMetric);
    return barOption(p.x, p.series, "money", { stack: true, legend: true });
  }, [r?.catQuarter, revenueMetric]);
  const ops = useMemo(() => {
    const rows = r?.ops?.rows ?? [];
    return barOption(rows.map((x) => String(x.country)), [
      { name: "Return rate", data: rows.map((x) => num(x.return_rate)), kind: "pct" },
      { name: "Avg shipping days", data: rows.map((x) => num(x.avg_shipping_days)), type: "line", yAxis: 1, kind: "days", color: SERIES.aqua },
    ], "pct", { kind2: "days", legend: true });
  }, [r?.ops]);
  return (
    <div className="grid gap-4 lg:grid-cols-6">
      <Widget className="lg:col-span-3" title={`Revenue and margin by country (${me.user.region})`} result={r?.country} loading={b.isFetching} error={b.error} option={country} onClick={(p) => p.name && drill("countries", p.name)} subtitle="Click a country to drill down" />
      <Widget className="lg:col-span-3" title="Country by month" result={r?.countryMonth} loading={b.isFetching} error={b.error} option={lines} />
      <Widget className="lg:col-span-3" title="Category mix by quarter" result={r?.catQuarter} loading={b.isFetching} error={b.error} option={catQ} />
      <Widget className="lg:col-span-3" title="Return rate and shipping days by country" result={r?.ops} loading={b.isFetching} error={b.error} option={ops} />
      <Widget className="lg:col-span-6" title="Top products in your region" result={r?.products} loading={b.isFetching} error={b.error}>
        {r?.products && <ResultTable columns={r.products.columns} rows={r.products.rows} maxHeight={320} compact />}
      </Widget>
    </div>
  );
}

function CategoryLayout() {
  const me = useMe();
  const { filters, ready } = useApiFilters();
  const { revenueMetric, drill } = useFilters();
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    subMonth: { metrics: [revenueMetric], group_by: ["sub_category"], time_grain: "year_month", filters, limit: 500, include_totals: false },
    products: { metrics: [revenueMetric, "gross_profit", "margin_pct", "units", "return_rate"], group_by: ["product"], filters, limit: 25 },
    ladder: { metrics: ["orders", "margin_pct", "loss_order_pct"], group_by: ["discount_band"], filters },
    region: { metrics: [revenueMetric], group_by: ["region"], filters },
    subReturn: { metrics: ["return_rate"], group_by: ["sub_category"], filters },
    heat: { metrics: ["margin_pct"], group_by: ["sub_category", "discount_band"], filters, limit: 500, include_totals: false },
  }), [filters, revenueMetric]);
  const b = useBatch(queries, ready);
  const r = b.data;
  const area = useMemo(() => {
    const p = pivot(r?.subMonth, "year_month", "sub_category", revenueMetric);
    return lineOption(p.x, p.series.map((s) => ({ ...s, area: true, stack: "s" })), "money", { zoom: p.x.length > 24 });
  }, [r?.subMonth, revenueMetric]);
  const ladder = useMemo(() => discountLadderOption(r?.ladder?.rows ?? []), [r?.ladder]);
  const region = useMemo(() => donutOption((r?.region?.rows ?? []).map((x) => ({ name: String(x.region), value: num(x[revenueMetric]) ?? 0 })), "money"), [r?.region, revenueMetric]);
  const subRet = useMemo(() => {
    const rows = r?.subReturn?.rows ?? [];
    return barOption(rows.map((x) => String(x.sub_category)), [{ name: "Return rate", data: rows.map((x) => num(x.return_rate)), kind: "pct" }], "pct", { horizontal: true });
  }, [r?.subReturn]);
  const heat = useMemo(() => {
    const rows = r?.heat?.rows ?? [];
    const xs = ["0%", "5%", "10%", "15%", "20%", "25%", "30%", "40%", "50%"].filter((d) => rows.some((x) => x.discount_band === d));
    const ys = [...new Set(rows.map((x) => String(x.sub_category)))];
    return heatmapOption(xs, ys, rows.map((x) => [xs.indexOf(String(x.discount_band)), ys.indexOf(String(x.sub_category)), num(x.margin_pct)]), "pct", { reverse: true });
  }, [r?.heat]);
  return (
    <div className="grid gap-4 lg:grid-cols-6">
      <Widget className="lg:col-span-4" title={`Sub-categories by month (${me.user.category})`} result={r?.subMonth} loading={b.isFetching} error={b.error} option={area} />
      <Widget className="lg:col-span-2" title="Revenue by region" result={r?.region} loading={b.isFetching} error={b.error} option={region} onClick={(p) => p.name && drill("regions", p.name)} />
      <Widget className="lg:col-span-3" title="Discount ladder" subtitle="Orders, weighted margin, and loss share by discount level. Loss zone from 40 %." result={r?.ladder} loading={b.isFetching} error={b.error} option={ladder} ask="At which discount level do orders start to lose money, and why?" />
      <Widget className="lg:col-span-3" title="Margin by sub-category and discount" result={r?.heat} loading={b.isFetching} error={b.error} option={heat} height={300} />
      <Widget className="lg:col-span-4" title="Product leaderboard" result={r?.products} loading={b.isFetching} error={b.error}>
        {r?.products && <ResultTable columns={r.products.columns} rows={r.products.rows} maxHeight={340} compact onRowClick={(x) => drill("products", String(x.product))} />}
      </Widget>
      <Widget className="lg:col-span-2" title="Return rate by sub-category" result={r?.subReturn} loading={b.isFetching} error={b.error} option={subRet} onClick={(p) => p.name && drill("sub_categories", p.name)} />
    </div>
  );
}

export function discountLadderOption(rows: Record<string, unknown>[]) {
  const order = ["0%", "5%", "10%", "15%", "20%", "25%", "30%", "40%", "50%"];
  const sorted = [...rows].sort((a, b) => order.indexOf(String(a.discount_band)) - order.indexOf(String(b.discount_band)));
  const x = sorted.map((r) => String(r.discount_band));
  const opt = barOption(x, [
    { name: "Orders", data: sorted.map((r) => num(r.orders)), kind: "count", color: SERIES.blueLight },
    { name: "Margin", data: sorted.map((r) => num(r.margin_pct)), type: "line", yAxis: 1, kind: "pct", color: SERIES.aqua },
    { name: "Loss share", data: sorted.map((r) => num(r.loss_order_pct)), type: "line", yAxis: 1, kind: "pct", color: SERIES.red },
  ], "count", { kind2: "pct", legend: true });
  const lossStart = x.indexOf("40%");
  if (lossStart >= 0) {
    const series = (opt.series as object[])[0] as Record<string, unknown>;
    series.markArea = { silent: true, itemStyle: { color: "rgba(227,73,72,0.07)" }, data: [[{ xAxis: x[lossStart] }, { xAxis: x[x.length - 1] }]] };
  }
  return opt;
}
