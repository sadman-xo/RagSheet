import type { ReactNode } from "react";
import type { EChartsOption } from "echarts";
import { useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import type { QueryResult } from "@/api/types";
import { ChartWithMenu, type ChartClick } from "@/components/Chart";
import { Card, Empty, ErrorState, Loading, Notes } from "@/components/ui";
import { filterQuery } from "@/state/filters";
import { useUi } from "@/state/ui";
import { errorMessage } from "@/api/client";
import { cn } from "@/lib/cn";

export function Widget({ title, subtitle, result, loading, error, option, height = 280, onClick, className, children, footer, ask, testId }: {
  title: string;
  subtitle?: ReactNode;
  result?: QueryResult;
  loading?: boolean;
  error?: unknown;
  option?: EChartsOption | null;
  height?: number;
  onClick?: (p: ChartClick) => void;
  className?: string;
  children?: ReactNode;
  footer?: ReactNode;
  ask?: string;
  testId?: string;
}) {
  const nav = useNavigate();
  const openChat = useUi((s) => s.openChat);
  const resErr = result?.error?.message;
  const empty = result && !result.error && result.rows.length === 0 && !children;
  let body: ReactNode;
  if (error) body = <ErrorState message={errorMessage(error)} />;
  else if (resErr) body = <ErrorState message={resErr} />;
  else if (loading && !result) body = <Loading className="h-full" />;
  else if (empty) body = <Empty />;
  else if (children) body = children;
  else if (option)
    body = (
      <ChartWithMenu
        option={option}
        height={height}
        onClick={onClick}
        rows={result?.rows}
        name={title}
        onViewOrders={() => nav(`/orders${filterQuery(new URLSearchParams(window.location.search))}`)}
        testId={testId}
      />
    );
  return (
    <Card
      title={title}
      subtitle={subtitle}
      className={cn(loading && result && "opacity-70 transition-opacity", className)}
      testId={testId ? `${testId}-card` : undefined}
      actions={
        ask ? (
          <button type="button" className="btn-ghost mr-7 px-1.5 text-slate-400 hover:text-slate-800" onClick={() => openChat(ask)} title="Ask the assistant about this">
            <MessageSquare className="h-3.5 w-3.5" />
          </button>
        ) : undefined
      }
    >
      <div style={{ minHeight: children ? undefined : height }}>{body}</div>
      {(result?.notes?.length || footer) && (
        <div className="mt-2 space-y-1">
          {footer}
          <Notes notes={result?.notes} />
        </div>
      )}
    </Card>
  );
}

export function SourceNote({ result }: { result?: QueryResult }) {
  if (!result) return null;
  const rollup = result.source !== "orders";
  return (
    <span className="num text-[10.5px] text-slate-400" data-testid="source-note">
      source: {rollup ? `rollup (${result.source})` : "raw"} · {result.elapsed_ms.toFixed(0)} ms{result.cache ? " · cached" : ""}
    </span>
  );
}
