import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Catalog, Filters } from "@/api/types";

/** Filter state lives in the URL, so a link shows the same view. */
export interface UiFilters {
  period: string; // preset id or "custom"
  from?: string;
  to?: string;
  regions: string[];
  countries: string[];
  categories: string[];
  sub_categories: string[];
  products: string[];
  segments: string[];
  genders: string[];
  statuses: string[];
  shipping_methods: string[];
  payment_methods: string[];
  discount_bands: string[];
  revenue: "gross" | "net";
}

export type ListKey =
  | "regions"
  | "countries"
  | "categories"
  | "sub_categories"
  | "products"
  | "segments"
  | "genders"
  | "statuses"
  | "shipping_methods"
  | "payment_methods"
  | "discount_bands";

export const PARAM: Record<ListKey, string> = {
  regions: "region",
  countries: "country",
  categories: "category",
  sub_categories: "sub",
  products: "product",
  segments: "segment",
  genders: "gender",
  statuses: "status",
  shipping_methods: "ship",
  payment_methods: "pay",
  discount_bands: "disc",
};

export const LIST_KEYS = Object.keys(PARAM) as ListKey[];

export const LABELS: Record<ListKey, string> = {
  regions: "Region",
  countries: "Country",
  categories: "Category",
  sub_categories: "Sub-category",
  products: "Product",
  segments: "Segment",
  genders: "Gender",
  statuses: "Status",
  shipping_methods: "Shipping",
  payment_methods: "Payment",
  discount_bands: "Discount",
};

function readList(sp: URLSearchParams, name: string): string[] {
  const v = sp.get(name);
  return v ? v.split("|").filter(Boolean) : [];
}

export function parseFilters(sp: URLSearchParams): UiFilters {
  const f: UiFilters = {
    period: sp.get("period") ?? "all",
    from: sp.get("from") ?? undefined,
    to: sp.get("to") ?? undefined,
    revenue: sp.get("rev") === "net" ? "net" : "gross",
  } as UiFilters;
  for (const k of LIST_KEYS) f[k] = readList(sp, PARAM[k]);
  return f;
}

export function writeFilters(sp: URLSearchParams, f: UiFilters): URLSearchParams {
  const out = new URLSearchParams(sp);
  const setOrDel = (name: string, v: string | undefined) => (v ? out.set(name, v) : out.delete(name));
  setOrDel("period", f.period && f.period !== "all" ? f.period : undefined);
  setOrDel("from", f.period === "custom" ? f.from : undefined);
  setOrDel("to", f.period === "custom" ? f.to : undefined);
  setOrDel("rev", f.revenue === "net" ? "net" : undefined);
  for (const k of LIST_KEYS) setOrDel(PARAM[k], f[k].length ? f[k].join("|") : undefined);
  return out;
}

/** API filters for the current UI filters. The period preset is resolved with the catalog. */
export function toApiFilters(f: UiFilters, catalog?: Catalog): Filters {
  const out: Filters = {};
  if (f.period === "custom") {
    if (f.from) out.date_from = f.from;
    if (f.to) out.date_to = f.to;
  } else if (/^y\d{4}$/.test(f.period)) {
    out.years = [Number(f.period.slice(1))];
  } else if (/^y\d{4}q[1-4]$/.test(f.period)) {
    out.years = [Number(f.period.slice(1, 5))];
    out.quarters = [Number(f.period.slice(6))];
  } else if (f.period !== "all" && catalog) {
    const p = catalog.periods.find((x) => x.id === f.period);
    if (p?.date_from) out.date_from = p.date_from;
    if (p?.date_to) out.date_to = p.date_to;
  }
  for (const k of LIST_KEYS) if (f[k].length) (out as Record<string, string[]>)[k] = f[k];
  return out;
}

export function useFilters() {
  const [sp, setSp] = useSearchParams();
  const f = useMemo(() => parseFilters(sp), [sp]);

  const set = useCallback(
    (patch: Partial<UiFilters>) => {
      setSp((prev) => writeFilters(prev, { ...parseFilters(prev), ...patch }), { replace: false });
    },
    [setSp],
  );

  const toggle = useCallback(
    (key: ListKey, value: string) => {
      setSp((prev) => {
        const cur = parseFilters(prev);
        const list = cur[key].includes(value) ? cur[key].filter((v) => v !== value) : [...cur[key], value];
        return writeFilters(prev, { ...cur, [key]: list });
      });
    },
    [setSp],
  );

  /** Drill: set one value for a level and clear the levels below it. */
  const drill = useCallback(
    (key: ListKey, value: string) => {
      setSp((prev) => {
        const cur = parseFilters(prev);
        const next: UiFilters = { ...cur, [key]: [value] };
        const below: Record<string, ListKey[]> = {
          regions: ["countries"],
          categories: ["sub_categories", "products"],
          sub_categories: ["products"],
        };
        for (const b of below[key] ?? []) next[b] = [];
        return writeFilters(prev, next);
      });
    },
    [setSp],
  );

  const reset = useCallback(() => {
    setSp((prev) => {
      const out = new URLSearchParams(prev);
      ["period", "from", "to", "rev", ...Object.values(PARAM)].forEach((p) => out.delete(p));
      return out;
    });
  }, [setSp]);

  const activeCount = LIST_KEYS.reduce((n, k) => n + (f[k].length ? 1 : 0), 0) + (f.period !== "all" ? 1 : 0);
  const revenueMetric = f.revenue === "net" ? "net_revenue" : "gross_revenue";
  return { f, set, toggle, drill, reset, activeCount, revenueMetric, searchParams: sp };
}

/** Query string with the current filters (for links to other pages). */
export function filterQuery(sp: URLSearchParams): string {
  const keep = new URLSearchParams();
  for (const p of ["period", "from", "to", "rev", ...Object.values(PARAM)]) {
    const v = sp.get(p);
    if (v) keep.set(p, v);
  }
  const s = keep.toString();
  return s ? `?${s}` : "";
}
