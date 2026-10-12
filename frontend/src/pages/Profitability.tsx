import { useMemo, useState } from "react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { QuerySpec } from "@/api/types";
import { FilterBar } from "@/components/FilterBar";
import { heatmapOption, waterfallOption } from "@/components/charts";
import { ResultTable } from "@/components/DataTable";
import { PageHeader, Segmented } from "@/components/ui";
import { KpiRow } from "@/dashboards/KpiRow";
import { num } from "@/dashboards/helpers";
import { Widget } from "@/dashboards/Widget";
import { discountLadderOption } from "./Overview";

export default function Profitability() {
  const { filters, ready } = useApiFilters();
  const [heatBy, setHeatBy] = useState<"region" | "discount_band">("discount_band");
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    totals: { metrics: ["list_value", "discount_amount", "gross_revenue", "cost", "gross_profit", "shipping_cost_total"], filters },
    ladder: { metrics: ["orders", "margin_pct", "loss_order_pct"], group_by: ["discount_band"], filters },
    heat: { metrics: ["margin_pct"], group_by: ["sub_category", heatBy], filters, limit: 500, include_totals: false },
    loss: { metrics: ["loss_orders", "loss_order_pct", "gross_profit", "margin_pct", "effective_discount_pct"], group_by: ["product"], filters, sort_by: "gross_profit", sort_dir: "asc", limit: 20 },
    pas: { metrics: ["gross_profit", "profit_after_shipping", "margin_pct", "net_margin_pct"], group_by: ["shipping_method"], filters },
  }), [filters, heatBy]);
  const b = useBatch(queries, ready);
  const r = b.data;

  const waterfall = useMemo(() => {
    const t = r?.totals?.totals;
    if (!t) return null;
    const lv = num(t.list_value) ?? 0;
    const disc = num(t.discount_amount) ?? 0;
    const rev = num(t.gross_revenue) ?? 0;
    const cost = num(t.cost) ?? 0;
    const profit = num(t.gross_profit) ?? 0;
    const ship = num(t.shipping_cost_total) ?? 0;
    return waterfallOption([
      { label: "List value", value: lv, total: true },
      { label: "Discount", value: -disc },
      { label: "Revenue", value: rev, total: true },
      { label: "Cost", value: -cost },
      { label: "Profit", value: profit, total: true },
      { label: "Shipping", value: -ship },
      { label: "After shipping*", value: profit - ship, total: true },
    ], "money");
  }, [r?.totals]);

  const heat = useMemo(() => {
    const rows = r?.heat?.rows ?? [];
    const order = heatBy === "discount_band" ? ["0%", "5%", "10%", "15%", "20%", "25%", "30%", "40%", "50%"] : undefined;
    let xs = [...new Set(rows.map((x) => String(x[heatBy])))];
    if (order) xs = order.filter((d) => xs.includes(d));
    const ys = [...new Set(rows.map((x) => String(x.sub_category)))];
    return heatmapOption(xs, ys, rows.map((x) => [xs.indexOf(String(x[heatBy])), ys.indexOf(String(x.sub_category)), num(x.margin_pct)]), "pct", { reverse: true });
  }, [r?.heat, heatBy]);

  return (
    <div>
      <FilterBar />
      <PageHeader title="Profitability" subtitle="From list price to profit: discounts, cost, loss orders, and shipping" />
      <KpiRow metrics={["gross_revenue", "gross_profit", "margin_pct", "net_margin_pct", "loss_orders", "loss_order_pct", "effective_discount_pct", "profit_after_shipping"]} />
      <div className="grid gap-4 lg:grid-cols-6">
        <Widget className="lg:col-span-3" title="From list value to profit" subtitle="*Profit after shipping is an estimate: the data does not say who pays the shipping." result={r?.totals} loading={b.isFetching} error={b.error} option={waterfall} height={300} ask="Explain the path from list value to profit." />
        <Widget className="lg:col-span-3" title="Discount ladder" subtitle="Orders, weighted margin, and loss share. Loss zone from 40 %." result={r?.ladder} loading={b.isFetching} error={b.error} option={discountLadderOption(r?.ladder?.rows ?? [])} height={300} ask="At which discount do orders start to lose money?" />
        <Widget
          className="lg:col-span-6"
          title="Margin heatmap"
          subtitle="Weighted margin by sub-category"
          result={r?.heat}
          loading={b.isFetching}
          error={b.error}
          option={heat}
          height={380}
          footer={<Segmented value={heatBy} onChange={setHeatBy} options={[{ value: "discount_band", label: "by discount" }, { value: "region", label: "by region" }]} size="xs" />}
        />
        <Widget className="lg:col-span-4" title="Products with the least profit" subtitle="Loss orders and margin" result={r?.loss} loading={b.isFetching} error={b.error}>
          {r?.loss && <ResultTable columns={r.loss.columns} rows={r.loss.rows} maxHeight={380} compact />}
        </Widget>
        <Widget className="lg:col-span-2" title="Profit after shipping by method" subtitle="Estimate" result={r?.pas} loading={b.isFetching} error={b.error}>
          {r?.pas && <ResultTable columns={r.pas.columns} rows={r.pas.rows} totals={r.pas.totals} maxHeight={380} compact />}
        </Widget>
      </div>
    </div>
  );
}
