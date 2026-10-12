import { useMemo, useState } from "react";
import { useApiFilters, useBatch } from "@/api/hooks";
import type { QuerySpec } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { FilterBar } from "@/components/FilterBar";
import { heatmapOption, lineOption } from "@/components/charts";
import { PageHeader, Segmented } from "@/components/ui";
import { num, seriesOf } from "@/dashboards/helpers";
import { SourceNote, Widget } from "@/dashboards/Widget";
import { useFilters } from "@/state/filters";
import { MONTH_NAMES } from "@/lib/format";
import { SERIES } from "@/lib/colors";

type Grain = "year_month" | "year_quarter" | "year" | "week" | "order_date";

export default function Trends() {
  const me = useMe();
  const { filters, ready } = useApiFilters();
  const { revenueMetric } = useFilters();
  const [grain, setGrain] = useState<Grain>("year_month");
  const [metric, setMetric] = useState<string>(revenueMetric);
  const metricOptions = ["gross_revenue", "net_revenue", "orders", "units", "aov", "return_rate", "cancellation_rate", ...(me.scope.financial ? ["gross_profit", "margin_pct"] : [])];
  const hasPeriod = !!(filters.date_from || filters.date_to || filters.years);
  const queries = useMemo<Record<string, QuerySpec>>(() => ({
    main: { metrics: [metric], time_grain: grain, filters, compare: hasPeriod && grain !== "week" ? "prior_year_lfl" : "none", limit: 500, include_totals: false },
    heat: { metrics: [metric], group_by: ["month"], time_grain: "year", filters, limit: 500, include_totals: false },
    aov: { metrics: ["aov", "units"], time_grain: "year_month", filters, limit: 500, include_totals: false },
  }), [metric, grain, filters, hasPeriod]);
  const b = useBatch(queries, ready);
  const r = b.data;
  const kind = r?.main?.columns.find((c) => c.key === metric)?.kind ?? "money";

  const main = useMemo(() => {
    const s = seriesOf(r?.main, grain, [metric]);
    if (hasPeriod && r?.main?.compare) s.series.push({ name: "Same period last year", data: (r.main.rows ?? []).map((x) => num(x[`${metric}__prior`])), dashed: true, color: SERIES.prior, kind });
    return lineOption(s.x, s.series.map((x) => ({ ...x, area: x.dashed ? false : true })), kind, { zoom: s.x.length > 36 });
  }, [r?.main, grain, metric, hasPeriod, kind]);

  const heat = useMemo(() => {
    const rows = r?.heat?.rows ?? [];
    const years = [...new Set(rows.map((x) => String(x.year)))].sort();
    return heatmapOption(MONTH_NAMES, years, rows.map((x) => [Number(x.month) - 1, years.indexOf(String(x.year)), num(x[metric])]), kind);
  }, [r?.heat, metric, kind]);

  const aov = useMemo(() => {
    const s = seriesOf(r?.aov, "year_month", ["aov", "units"], { aov: "Average order value", units: "Units" });
    return lineOption(s.x, s.series.map((x, i) => ({ ...x, yAxis: i as 0 | 1, kind: i ? "count" : "money" })), "money", { kind2: "count", zoom: s.x.length > 36 });
  }, [r?.aov]);

  return (
    <div>
      <FilterBar />
      <PageHeader
        title="Trends"
        subtitle="How the business changes over time"
        actions={
          <select className="input w-56" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
            {metricOptions.map((m) => <option key={m} value={m}>{me.metrics.find((x) => x.id === m)?.label ?? m}</option>)}
          </select>
        }
      />
      <div className="grid gap-4 lg:grid-cols-6">
        <Widget
          className="lg:col-span-6"
          title={me.metrics.find((x) => x.id === metric)?.label ?? metric}
          subtitle={hasPeriod ? "With the same period last year (like-for-like)" : "Select a period to compare with the prior year"}
          result={r?.main}
          loading={b.isFetching}
          error={b.error}
          option={main}
          height={340}
          footer={
            <div className="flex items-center justify-between">
              <Segmented value={grain} onChange={setGrain} options={[{ value: "order_date", label: "Day" }, { value: "week", label: "Week" }, { value: "year_month", label: "Month" }, { value: "year_quarter", label: "Quarter" }, { value: "year", label: "Year" }]} size="xs" />
              <SourceNote result={r?.main} />
            </div>
          }
          ask="What drives this trend?"
        />
        <Widget className="lg:col-span-3" title="Month by year" subtitle="Seasonality heatmap" result={r?.heat} loading={b.isFetching} error={b.error} option={heat} height={260} />
        <Widget className="lg:col-span-3" title="Average order value and units" result={r?.aov} loading={b.isFetching} error={b.error} option={aov} height={260} />
      </div>
    </div>
  );
}
