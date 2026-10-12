import { ArrowRight } from "lucide-react";
import { useInsights } from "@/api/hooks";
import { useUi } from "@/state/ui";
import { Card, Loading } from "@/components/ui";

export function InsightCards({ only, limit = 6 }: { only?: string[]; limit?: number }) {
  const q = useInsights();
  const openChat = useUi((s) => s.openChat);
  const items = (q.data ?? []).filter((i) => !only || only.includes(i.id)).slice(0, limit);
  return (
    <Card title="Insights" subtitle="Calculated from your data scope" testId="insights" bodyClass="p-0 pt-1">
      {q.isLoading ? (
        <Loading />
      ) : (
        <ol className="grid border-t border-slate-100 md:grid-cols-2 xl:grid-cols-3">
          {items.map((i, n) => (
            <li key={i.id} className="flex gap-3 border-b border-slate-100 p-4 md:[&:nth-child(odd)]:border-r xl:[&:nth-child(odd)]:border-r-0 xl:[&:not(:nth-child(3n))]:border-r">
              <span className="num pt-px text-xs text-slate-400">{String(n + 1).padStart(2, "0")}</span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="text-[13.5px] font-semibold text-slate-900">{i.title}</div>
                <p className="flex-1 text-[13px] leading-relaxed text-slate-600">{i.text}</p>
                <button
                  type="button"
                  className="group mt-1 inline-flex w-fit items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900"
                  onClick={() => openChat(`Tell me more about this insight: ${i.title}. ${i.text}`)}
                >
                  Ask the assistant <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" />
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
