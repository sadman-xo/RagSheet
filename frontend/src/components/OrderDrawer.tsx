import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { get, errorMessage } from "@/api/client";
import type { OrderDetail } from "@/api/types";
import { Badge, Drawer, ErrorState, Loading } from "./ui";
import { byKind } from "@/lib/format";
import { STATUS_COLORS } from "@/lib/colors";

export function OrderDrawer({ orderId, onClose }: { orderId: string | null; onClose: () => void }) {
  const q = useQuery<OrderDetail>({
    queryKey: ["order", orderId],
    queryFn: () => get<OrderDetail>(`/orders/${encodeURIComponent(orderId!)}`),
    enabled: !!orderId,
    retry: false,
  });
  const o = q.data?.order;
  return (
    <Drawer open={!!orderId} onOpenChange={(v) => !v && onClose()} title={`Order ${orderId ?? ""}`} width="max-w-md">
      <div className="p-4" data-testid="order-drawer">
        {q.isLoading && <Loading />}
        {q.error && <ErrorState message={errorMessage(q.error)} />}
        {o && q.data && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLORS[String(o.order_status)] }} />
              <span className="font-medium">{String(o.order_status)}</span>
              {q.data.pseudonym && <Badge tone="amber">Customer ID is a pseudonym</Badge>}
            </div>
            <dl className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {q.data.fields.map((f) => (
                <div key={f.key} className="grid grid-cols-[150px_1fr] gap-2 px-3 py-1.5 text-sm" title={f.description}>
                  <dt className="text-slate-500">{f.label}</dt>
                  <dd className="font-medium text-slate-800">{formatField(f.kind, o[f.key])}</dd>
                </div>
              ))}
              {q.data.hidden_fields.map((f) => (
                <div key={f.key} className="grid grid-cols-[150px_1fr] gap-2 bg-slate-50 px-3 py-1.5 text-sm">
                  <dt className="text-slate-400">{f.label}</dt>
                  <dd className="flex items-center gap-1 text-slate-400">
                    <Lock className="h-3 w-3" /> Hidden for your role
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </Drawer>
  );
}

export function formatField(kind: string, v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (kind === "money") return byKind("money", Number(v));
  if (kind === "pct") return typeof v === "number" && v <= 1 ? `${Math.round(v * 100)}%` : `${v}%`;
  if (kind === "bool") return v ? "Yes" : "No";
  return String(v);
}
