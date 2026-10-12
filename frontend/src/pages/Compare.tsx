import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { errorMessage, post } from "@/api/client";
import { useCatalog } from "@/api/hooks";
import type { Catalog, CompareResponse, Filters } from "@/api/types";
import { useMe } from "@/auth/AuthProvider";
import { MultiSelect } from "@/components/FilterBar";
import { barOption, lineOption } from "@/components/charts";
import { Card, ErrorState, Loading, PageHeader } from "@/components/ui";
import { Widget } from "@/dashboards/Widget";
import { num } from "@/dashboards/helpers";
import { byKind, deltaText } from "@/lib/format";
import { cn } from "@/lib/cn";
import { SERIES } from "@/lib/colors";

type MemberKey = "regions" | "countries" | "categories" | "sub_categories" | "segments" | "shipping_methods" | "payment_methods";
const MEMBER_LABELS: Record<MemberKey, string> = {
  regions: "Region", countries: "Country", categories: "Category", sub_categories: "Sub-category",
  segments: "Segment", shipping_methods: "Shipping method", payment_methods: "Payment method",
};

interface Side {
  label: string;
  period: string;
  memberKey: MemberKey;
  members: string[];
}

function membersOf(cat: Catalog, key: MemberKey): string[] {
  if (key === "regions") return cat.regions.map((r) => r.name);
  if (key === "categories") return cat.categories.map((c) => c.name);
  return (cat as unknown as Record<string, string[]>)[key] ?? [];
}

function sideFilters(s: Side, cat: Catalog): Filters {
  const f: Filters = {};
  if (/^y\d{4}$/.test(s.period)) f.years = [Number(s.period.slice(1))];
  else if (/^y\d{4}q\d$/.test(s.period)) {
    f.years = [Number(s.period.slice(1, 5))];
    f.quarters = [Number(s.period.slice(6))];
  } else if (s.period !== "all") {
    const p = cat.periods.find((x) => x.id === s.period);
    if (p?.date_from) f.date_from = p.date_from;
    if (p?.date_to) f.date_to = p.date_to;
  }
  if (s.members.length) (f as Record<string, string[]>)[s.memberKey] = s.members;
  return f;
}

function SideEditor({ side, onChange, cat, tone }: { side: Side; onChange: (s: Side) => void; cat: Catalog; tone: string }) {
  return (
    <div className={cn("space-y-2 rounded-md border border-t-[3px] bg-white p-3", tone)}>
      <input className="input font-semibold" value={side.label} onChange={(e) => onChange({ ...side, label: e.target.value })} aria-label="Side label" />
      <select className="input" value={side.period} onChange={(e) => onChange({ ...side, period: e.target.value })} aria-label="Period">
        {cat.periods.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        {cat.years.map((y) => <option key={y} value={`y${y}`}>{y}</option>)}
        {cat.years.flatMap((y) => [1, 2, 3, 4].map((q) => <option key={`${y}${q}`} value={`y${y}q${q}`}>Q{q} {y}</option>))}
      </select>
      <div className="flex flex-wrap items-center gap-2">
        <select className="h-7 rounded-md border border-slate-200 bg-white px-2 text-xs" value={side.memberKey} onChange={(e) => onChange({ ...side, memberKey: e.target.value as MemberKey, members: [] })} aria-label="Member type">
          {(Object.keys(MEMBER_LABELS) as MemberKey[]).filter((k) => membersOf(cat, k).length > 1).map((k) => <option key={k} value={k}>{MEMBER_LABELS[k]}</option>)}
        </select>
        <MultiSelect label={MEMBER_LABELS[side.memberKey]} options={membersOf(cat, side.memberKey)} value={side.members}
          onToggle={(v) => onChange({ ...side, members: side.members.includes(v) ? side.members.filter((x) => x !== v) : [...side.members, v] })}
          onClear={() => onChange({ ...side, members: [] })} />
      </div>
    </div>
  );
}

export default function Compare() {
  const me = useMe();
  const cat = useCatalog();
  const years = cat.data?.years ?? [];
  const [a, setA] = useState<Side>({ label: "A", period: "", memberKey: "regions", members: [] });
  const [b, setB] = useState<Side>({ label: "B", period: "", memberKey: "regions", members: [] });
  const [metrics, setMetrics] = useState<string[]>(["gross_revenue", "orders", "aov", me.scope.financial ? "margin_pct" : "return_rate"]);
  const [groupBy, setGroupBy] = useState<string>("");
  const ya = a.period || (years.length > 1 ? `y${years[years.length - 2]}` : "all");
  const yb = b.period || (years.length ? `y${years[years.length - 1]}` : "all");
  const sa = { ...a, period: ya, label: a.label === "A" ? ya.replace(/^y/, "") : a.label };
  const sb = { ...b, period: yb, label: b.label === "B" ? yb.replace(/^y/, "") : b.label };

  const body = useMemo(() => cat.data && {
    a: { label: sa.label, filters: sideFilters(sa, cat.data) },
    b: { label: sb.label, filters: sideFilters(sb, cat.data) },
    metrics, group_by: groupBy || null, time_grain: "year_month",
  }, [cat.data, sa.label, sb.label, sa.period, sb.period, sa.members.join(), sb.members.join(), sa.memberKey, sb.memberKey, metrics.join(), groupBy]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery<CompareResponse>({ queryKey: ["compare", body], queryFn: () => post<CompareResponse>("/analytics/compare", body), enabled: !!body, placeholderData: (p) => p });

  const trend = useMemo(() => {
    if (!q.data?.trends) return null;
    const m = metrics[0];
    const n = Math.max(q.data.trends.a.length, q.data.trends.b.length);
    const x = Array.from({ length: n }, (_, i) => `M${i + 1}`);
    const kind = q.data.kpis.find((k) => k.metric === m)?.kind ?? "money";
    return lineOption(x, [
      { name: q.data.a.label, data: x.map((_, i) => num(q.data!.trends!.a[i]?.[m])), color: SERIES.blue },
      { name: q.data.b.label, data: x.map((_, i) => num(q.data!.trends!.b[i]?.[m])), color: SERIES.orange },
    ], kind);
  }, [q.data, metrics]);

  const breakdown = useMemo(() => {
    if (!q.data?.breakdown || !groupBy) return null;
    const m = metrics[0];
    const kind = q.data.kpis.find((k) => k.metric === m)?.kind ?? "money";
    const rows = q.data.breakdown;
    return barOption(rows.map((r) => String(r[groupBy])), [
      { name: q.data.a.label, data: rows.map((r) => num(r[`${m}__a`])), color: SERIES.blue },
      { name: q.data.b.label, data: rows.map((r) => num(r[`${m}__b`])), color: SERIES.orange },
    ], kind, { legend: true });
  }, [q.data, groupBy, metrics]);

  if (!cat.data) return <Loading />;
  return (
    <div className="pt-4">
      <PageHeader title="Compare" subtitle="Compare two periods or two groups in your scope" />
      <div className="mb-4 grid items-center gap-3 lg:grid-cols-[1fr_auto_1fr]">
        <SideEditor side={sa} onChange={setA} cat={cat.data} tone="border-slate-200 border-t-[#2a78d6]" />
        <ArrowLeftRight className="mx-auto h-5 w-5 text-slate-400" />
        <SideEditor side={sb} onChange={setB} cat={cat.data} tone="border-slate-200 border-t-[#eb6834]" />
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <MultiSelect label="Metrics" options={me.allowed_metrics} value={metrics} onToggle={(v) => setMetrics(metrics.includes(v) ? metrics.filter((x) => x !== v) : [...metrics, v].slice(-6))} onClear={() => setMetrics(["gross_revenue"])} />
        <select className="h-7 rounded-md border border-slate-200 bg-white px-2 text-xs" value={groupBy} onChange={(e) => setGroupBy(e.target.value)} aria-label="Breakdown">
          <option value="">No breakdown</option>
          {["region", "country", "category", "sub_category", "customer_segment", "shipping_method", "payment_method", "order_status"].map((d) => <option key={d} value={d}>by {d.replace("_", " ")}</option>)}
        </select>
      </div>
      {q.error ? <ErrorState message={errorMessage(q.error)} /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="KPI comparison" className="lg:col-span-2" testId="compare-kpis">
            {!q.data ? <Loading /> : (
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="table-head">Metric</th>
                    <th className="table-head text-right"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-[#2a78d6]" />{q.data.a.label}</span></th>
                    <th className="table-head text-right"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-[#eb6834]" />{q.data.b.label}</span></th>
                    <th className="table-head text-right">Change (B vs A)</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.kpis.map((k) => {
                    const chg = k.kind === "pct" ? k.delta : k.pct;
                    const good = chg === null || k.higher_is_better === null ? null : (chg >= 0) === k.higher_is_better;
                    return (
                      <tr key={k.metric} className="border-t border-slate-100">
                        <td className="table-cell font-medium">{k.label}</td>
                        <td className="table-cell text-right tabular-nums">{byKind(k.kind, k.a)}</td>
                        <td className="table-cell text-right tabular-nums">{byKind(k.kind, k.b)}</td>
                        <td className={cn("table-cell text-right tabular-nums font-medium", good === null ? "text-slate-500" : good ? "text-emerald-600" : "text-red-600")}>{deltaText(k.kind, k.pct, k.delta)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Card>
          <Widget title={`Overlaid trend: ${me.metrics.find((m) => m.id === metrics[0])?.label ?? metrics[0]}`} subtitle="Month 1, 2, … of each side" loading={q.isFetching} option={trend} height={300} />
          {groupBy && <Widget title={`Breakdown by ${groupBy.replace("_", " ")}`} loading={q.isFetching} option={breakdown} height={300} />}
        </div>
      )}
    </div>
  );
}
