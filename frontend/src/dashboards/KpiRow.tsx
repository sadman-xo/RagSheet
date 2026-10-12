import { useApiFilters, useKpis } from "@/api/hooks";
import { KpiCard } from "@/components/KpiCard";
import { ErrorState, Notes } from "@/components/ui";
import { errorMessage } from "@/api/client";

export function KpiRow({ metrics }: { metrics?: string[] }) {
  const { filters, ready } = useApiFilters();
  const hasPeriod = !!(filters.date_from || filters.date_to || filters.years);
  const q = useKpis(filters, hasPeriod ? "prior_year_lfl" : "none", metrics, ready);
  if (q.error) return <ErrorState message={errorMessage(q.error)} />;
  const kpis = q.data?.kpis;
  return (
    <div className="mb-5 space-y-2" data-testid="kpi-row">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-200 bg-slate-200 md:grid-cols-4 xl:grid-cols-8">
        {kpis
          ? kpis.map((k) => <KpiCard key={k.id} kpi={k} compareLabel={hasPeriod ? q.data?.compare ?? "Prior year" : null} />)
          : Array.from({ length: metrics?.length ?? 8 }, (_, i) => (
              <div key={i} className="h-[120px] bg-white p-4">
                <div className="h-3 w-20 animate-pulse rounded bg-slate-100" />
                <div className="mt-3 h-6 w-28 animate-pulse rounded bg-slate-100" />
              </div>
            ))}
      </div>
      <Notes notes={q.data?.notes} />
    </div>
  );
}
