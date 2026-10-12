import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { Kpi } from "@/api/types";
import { byKind, deltaText } from "@/lib/format";
import { NEGATIVE, NEUTRAL, POSITIVE, SERIES } from "@/lib/colors";
import { Chart } from "./Chart";
import { sparkOption } from "./charts";
import { Tip } from "./ui";
import { cn } from "@/lib/cn";

export function KpiCard({ kpi, compareLabel }: { kpi: Kpi; compareLabel?: string | null }) {
  const change = kpi.kind === "pct" ? kpi.delta : kpi.pct;
  const good = change === null || kpi.higher_is_better === null ? null : (change >= 0) === kpi.higher_is_better;
  const color = good === null ? NEUTRAL : good ? POSITIVE : NEGATIVE;
  const Icon = change === null || change === 0 ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight;
  const lowN = kpi.n !== null && kpi.n < 30;
  return (
    <div className="flex min-w-0 flex-col bg-white px-3.5 pb-2 pt-3.5" data-testid={`kpi-${kpi.id}`}>
      <Tip content={<span>{kpi.description}</span>}>
        <span className="label w-fit cursor-help truncate decoration-slate-300 decoration-dotted underline-offset-2 hover:underline">{kpi.label}</span>
      </Tip>
      <div className={cn("mt-1.5 whitespace-nowrap text-[clamp(17px,1.35vw,22px)] font-semibold leading-none tracking-[-0.02em] text-slate-900", lowN && "text-slate-400")} title={lowN ? "Fewer than 30 orders" : undefined}>
        {byKind(kpi.kind, kpi.value)}
      </div>
      <div className="mt-2 flex h-4 items-center gap-2">
        {compareLabel && kpi.prior !== null ? (
          <Tip content={<span>{compareLabel}: {byKind(kpi.kind, kpi.prior)}</span>}>
            <span className="flex items-center gap-0.5 text-xs font-medium" style={{ color }}>
              <Icon className="h-3.5 w-3.5" /> {deltaText(kpi.kind, kpi.pct, kpi.delta)}
              <span className="ml-1 font-normal text-slate-400">vs LY</span>
            </span>
          </Tip>
        ) : (
          <span className="truncate text-[11.5px] text-slate-400">{compareLabel === null ? "No comparison" : ""}</span>
        )}
      </div>
      {kpi.spark.length > 1 && (
        <div className="mt-1.5">
          <Chart option={sparkOption(kpi.spark.map((s) => s.y), SERIES.blue)} height={30} />
        </div>
      )}
    </div>
  );
}
