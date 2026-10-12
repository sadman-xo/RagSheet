import type { MetricKind } from "@/api/types";

const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function money(v: number | null | undefined, compact = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return compact ? compactNumber(v) : nf2.format(v);
}

export function compactNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const s = v < 0 ? "-" : "";
  if (a >= 1e9) return `${s}${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1)}K`;
  return `${s}${a.toFixed(a < 10 && a % 1 !== 0 ? 2 : 0)}`;
}

export function count(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return nf0.format(Math.round(v));
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${v.toFixed(digits)}%`;
}

export function days(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${v.toFixed(1)} d`;
}

export function byKind(kind: MetricKind | string, v: number | null | undefined, compact = false): string {
  switch (kind) {
    case "money":
      return money(v, compact);
    case "count":
      return compact ? compactNumber(v) : count(v);
    case "pct":
      return pct(v, compact ? 1 : 2);
    case "days":
      return days(v);
    default:
      return v === null || v === undefined ? "–" : nf2.format(v);
  }
}

export function axisFormatter(kind: MetricKind | string) {
  return (v: number) => {
    if (kind === "pct") return `${v}%`;
    if (kind === "days") return `${v}`;
    return compactNumber(v);
  };
}

/** Change text: % for amounts and counts, points for rates. */
export function deltaText(kind: MetricKind | string, pctChange: number | null, delta: number | null): string {
  if (kind === "pct") {
    if (delta === null || delta === undefined) return "–";
    return `${delta >= 0 ? "+" : ""}${delta.toFixed(2)} pts`;
  }
  if (pctChange === null || pctChange === undefined) return "–";
  return `${pctChange >= 0 ? "+" : ""}${pctChange.toFixed(1)}%`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
}

export const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
