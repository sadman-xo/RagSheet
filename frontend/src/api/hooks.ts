import { useQuery } from "@tanstack/react-query";
import { get, post } from "./client";
import type { Catalog, CompareMode, DataNote, Filters, Insight, KpiResponse, QueryResult, QuerySpec } from "./types";
import { toApiFilters, useFilters } from "@/state/filters";

export function useCatalog() {
  return useQuery<Catalog>({ queryKey: ["catalog"], queryFn: () => get<Catalog>("/meta/catalog"), staleTime: Infinity });
}

/** API filters for the current page filters (URL). */
export function useApiFilters(): { filters: Filters; ready: boolean } {
  const { f } = useFilters();
  const cat = useCatalog();
  return { filters: toApiFilters(f, cat.data), ready: !!cat.data };
}

export function useBatch(queries: Record<string, QuerySpec>, enabled = true) {
  return useQuery<Record<string, QueryResult>>({
    queryKey: ["batch", queries],
    queryFn: async ({ signal }) => (await post<{ results: Record<string, QueryResult> }>("/analytics/batch", { queries }, signal)).results,
    enabled,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useQuerySpec(spec: QuerySpec | null) {
  return useQuery<QueryResult>({
    queryKey: ["query", spec],
    queryFn: ({ signal }) => post<QueryResult>("/analytics/query", spec, signal),
    enabled: !!spec,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useKpis(filters: Filters, compare: CompareMode, metrics?: string[], enabled = true) {
  return useQuery<KpiResponse>({
    queryKey: ["kpis", filters, compare, metrics],
    queryFn: ({ signal }) => post<KpiResponse>("/analytics/kpis", { filters, compare, metrics }, signal),
    enabled,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useInsights() {
  return useQuery<Insight[]>({
    queryKey: ["insights"],
    queryFn: async () => (await get<{ insights: Insight[] }>("/analytics/insights")).insights,
    staleTime: Infinity,
  });
}

export function useDataNotes() {
  return useQuery<{ notes: DataNote[]; formulas: { name: string; formula: string }[] }>({
    queryKey: ["data-notes"],
    queryFn: () => get("/meta/data-notes"),
    staleTime: Infinity,
  });
}
