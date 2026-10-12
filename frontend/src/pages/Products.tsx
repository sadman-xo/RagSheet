import { useMemo } from "react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { FilterBar } from "@/components/FilterBar";
import { barOption, scatterOption, treemapOption, type TreeNode } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { PageHeader } from "@/components/ui";
import { num } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { SERIES } from "@/lib/colors";

export default function Products() {
  const me = useMe();
  const fin = me.scope.financial;
  const { filters, ready } = useApiFilters();
  const { revenueMetric, drill } = useFilters();
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    tree: { metrics: [revenueMetric], group_by: ["sub_category", "product"], filters, limit: 500, include_totals: false },
    board: { metrics: [revenueMetric, "units", "orders", fin ? "margin_pct" : "aov", "return_rate", "effective_discount_pct"], group_by: ["product"], filters, limit: 100 },
    sub: { metrics: [revenueMetric, fin ? "gross_profit" : "units"], group_by: ["sub_category"], filters },
    price: { metrics: ["orders", revenueMetric], group_by: ["price_band"], filters },
  }), [filters, revenueMetric, fin]);
  const b = useBatch(queries, ready);
  const r = b.data;
  const tree = useMemo(() => {
    const bySub = new Map<string, TreeNode>();
    for (const x of r?.tree?.rows ?? []) {
      const s = String(x.sub_category);
      if (!bySub.has(s)) bySub.set(s, { name: s, value: 0, children: [] });
      const v = num(x[revenueMetric]) ?? 0;
      bySub.get(s)!.value += v;
      bySub.get(s)!.children!.push({ name: String(x.product), value: v });
    }
    return treemapOption([...bySub.values()], "money");
  }, [r?.tree, revenueMetric]);

  const scatter = useMemo(() => {
    const rows = r?.board?.rows ?? [];
    const y = fin ? "margin_pct" : "return_rate";
    return scatterOption(
      rows.map((x) => ({ name: String(x.product), x: num(x.units) ?? 0, y: num(x[y]) ?? 0, size: num(x[revenueMetric]) ?? 1 })),
      "count", "pct", "Units", fin ? "Margin" : "Return rate",
    );
  }, [r?.board, fin, revenueMetric]);

  const subOpt = useMemo(() => {
    const rows = r?.sub?.rows ?? [];
    const m2 = fin ? "gross_profit" : "units";
    return barOption(rows.map((x) => String(x.sub_category)), [
      { name: "Revenue", data: rows.map((x) => num(x[revenueMetric])), kind: "money" },
      { name: fin ? "Gross profit" : "Units", data: rows.map((x) => num(x[m2])), kind: fin ? "money" : "count", ...(fin ? {} : { type: "line" as const, yAxis: 1 as const }) },
    ], "money", { horizontal: fin, legend: true, kind2: fin ? undefined : "count" });
  }, [r?.sub, fin, revenueMetric]);

  const priceOpt = useMemo(() => {
    const order = ["<25", "25-100", "100-250", "250-500", "500-1000", "1000+"];
    const rows = [...(r?.price?.rows ?? [])].sort((a, b) => order.indexOf(String(a.price_band)) - order.indexOf(String(b.price_band)));
    return barOption(rows.map((x) => String(x.price_band)), [
      { name: "Orders", data: rows.map((x) => num(x.orders)), kind: "count", color: SERIES.blueLight },
      { name: "Revenue", data: rows.map((x) => num(x[revenueMetric])), type: "line", yAxis: 1, kind: "money", color: SERIES.blue },
    ], "count", { kind2: "money", legend: true });
  }, [r?.price, revenueMetric]);

  return (
    <div>
      <FilterBar />
      <PageHeader title="Products" subtitle="Product mix, leaders, and price bands" />
      <div className="grid gap-4 lg:grid-cols-6">
        <Widget className="lg:col-span-3" title="Sub-category › product" subtitle="Size = revenue" result={r?.tree} loading={b.isFetching} error={b.error} option={tree} height={340} />
        <Widget className="lg:col-span-3" title={fin ? "Units vs margin" : "Units vs return rate"} subtitle="Bubble size = revenue. Click a product to filter." result={r?.board} loading={b.isFetching} error={b.error} option={scatter} height={340} onClick={(p) => p.name && drill("products", p.name)} />
        <Widget className="lg:col-span-6" title="Product leaderboard" subtitle="Click a row to filter by the product" result={r?.board} loading={b.isFetching} error={b.error}>
          {r?.board && <ResultTable columns={r.board.columns} rows={r.board.rows} totals={r.board.totals} maxHeight={420} compact onRowClick={(x) => drill("products", String(x.product))} />}
        </Widget>
        <Widget className="lg:col-span-3" title={fin ? "Revenue and profit by sub-category" : "Revenue and units by sub-category"} result={r?.sub} loading={b.isFetching} error={b.error} option={subOpt} height={320} onClick={(p) => p.name && drill("sub_categories", p.name)} />
        <Widget className="lg:col-span-3" title="Price bands" subtitle="Orders and revenue by unit price" result={r?.price} loading={b.isFetching} error={b.error} option={priceOpt} height={320} />
      </div>
    </div>
  );
}
