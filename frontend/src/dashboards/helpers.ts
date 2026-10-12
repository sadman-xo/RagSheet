import type { QueryResult, Row } from "@/api/types";
import type { SeriesDef } from "@/components/charts";
import { monthLabel } from "@/lib/format";

export function num(v: unknown): number | null {
  return typeof v === "number" ? v : v === null || v === undefined ? null : Number(v);
}

export function timeLabel(key: string, v: unknown): string {
  if (key === "year_month") return monthLabel(String(v));
  return String(v);
}

/** One series for each metric along a time or category key. */
export function seriesOf(res: QueryResult | undefined, xKey: string, metrics: string[], names?: Record<string, string>): { x: string[]; series: SeriesDef[] } {
  const rows = res?.rows ?? [];
  const x = rows.map((r) => timeLabel(xKey, r[xKey]));
  const series = metrics.map((m) => ({
    name: names?.[m] ?? res?.columns.find((c) => c.key === m)?.label ?? m,
    data: rows.map((r) => num(r[m])),
    kind: res?.columns.find((c) => c.key === m)?.kind,
  }));
  return { x, series };
}

/** Pivot rows (x, s, value) into one series for each value of s. */
export function pivot(res: QueryResult | undefined, xKey: string, sKey: string, metric: string, order?: string[]): { x: string[]; series: SeriesDef[] } {
  const rows = res?.rows ?? [];
  const xs = [...new Set(rows.map((r) => String(r[xKey])))];
  if (xKey === "year_month" || xKey === "year_quarter" || xKey === "year" || xKey === "month" || xKey === "quarter") xs.sort((a, b) => (Number(a) && Number(b) ? Number(a) - Number(b) : a.localeCompare(b)));
  let ss = [...new Set(rows.map((r) => String(r[sKey])))];
  if (order) ss = ss.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const map = new Map<string, number | null>();
  for (const r of rows) map.set(`${r[xKey]}|${r[sKey]}`, num(r[metric]));
  return {
    x: xs.map((v) => timeLabel(xKey, v)),
    series: ss.map((s) => ({ name: s, data: xs.map((x) => map.get(`${x}|${s}`) ?? null) })),
  };
}

/** Convert counts to percent shares for each x (100 % stacked bars). */
export function toShares(series: SeriesDef[]): SeriesDef[] {
  const n = series[0]?.data.length ?? 0;
  const totals = Array.from({ length: n }, (_, i) => series.reduce((a, s) => a + (s.data[i] ?? 0), 0));
  return series.map((s) => ({ ...s, data: s.data.map((v, i) => (v === null || !totals[i] ? null : Math.round((v / totals[i]) * 10000) / 100)) }));
}

export function rowsOf(res: QueryResult | undefined): Row[] {
  return res?.rows ?? [];
}

export function metricKind(res: QueryResult | undefined, m: string): string {
  return res?.columns.find((c) => c.key === m)?.kind ?? "number";
}

export function resultError(res: QueryResult | undefined): string | null {
  return res?.error?.message ?? null;
}
