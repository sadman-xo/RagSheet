import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Download, Lock, Search } from "lucide-react";
import { downloadPost, errorMessage, post } from "@/api/client";
import { useApiFilters } from "@/api/hooks";
import type { OrdersPage } from "@/api/types";
import { FilterBar } from "@/components/FilterBar";
import { OrderDrawer, formatField } from "@/components/OrderDrawer";
import { Badge, ErrorState, Loading, PageHeader } from "@/components/ui";
import { count } from "@/lib/format";
import { STATUS_COLORS } from "@/lib/colors";
import { cn } from "@/lib/cn";

const ROW_H = 34;

export default function Orders() {
  const { filters, ready } = useApiFilters();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"date_desc" | "date_asc">("date_desc");
  const [open, setOpen] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const body = useMemo(() => ({ filters, q: query || null, sort }), [filters, query, sort]);
  const iq = useInfiniteQuery<OrdersPage>({
    queryKey: ["orders", body],
    queryFn: ({ pageParam, signal }) => post<OrdersPage>("/orders/search", { ...body, limit: 200, cursor: pageParam ?? null, with_total: !pageParam }, signal),
    initialPageParam: null as OrdersPage["next_cursor"],
    getNextPageParam: (last) => last.next_cursor,
    enabled: ready,
  });
  const pages = iq.data?.pages ?? [];
  const rows = useMemo(() => pages.flatMap((p) => p.rows), [pages]);
  const first = pages[0];
  const columns = (first?.columns ?? []).filter((c) => c.in_table);

  const scroller = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_H, overscan: 20 });
  const items = v.getVirtualItems();
  useEffect(() => {
    const last = items[items.length - 1];
    if (last && last.index >= rows.length - 30 && iq.hasNextPage && !iq.isFetchingNextPage) iq.fetchNextPage();
  }, [items, rows.length, iq]);

  async function exportCsv() {
    setExporting(true);
    try {
      await downloadPost("/export/orders", { filters, q: query || null, sort }, "panorama_orders.csv");
    } catch (e) {
      alert(errorMessage(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <FilterBar />
      <PageHeader
        title="Orders"
        subtitle={first?.total != null ? `${count(first.total)} orders match · loaded ${count(rows.length)}` : "Order list (server-side paging)"}
        actions={
          <>
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
              <input className="input w-72 pl-8" placeholder="Order ID, customer ID, product, or country" value={q} onChange={(e) => setQ(e.target.value)} data-testid="orders-search" />
            </div>
            <button className="btn" onClick={exportCsv} disabled={exporting} data-testid="orders-export">
              <Download className="h-4 w-4" /> {exporting ? "Exporting…" : "Export CSV (max 10,000)"}
            </button>
          </>
        }
      />
      {first?.hidden_columns?.length ? (
        <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">
          <Lock className="h-3.5 w-3.5" /> Hidden for your role: {first.hidden_columns.join(", ")}
        </div>
      ) : null}
      {iq.error ? (
        <ErrorState message={errorMessage(iq.error)} />
      ) : (
        <div className="card min-h-0 flex-1 overflow-hidden">
          <div ref={scroller} className="scrollbar-thin h-[calc(100vh-260px)] min-h-[300px] overflow-auto" data-testid="orders-table">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key} className={cn("table-head", ["money", "int", "pct"].includes(c.kind) && "text-right")}>
                      {c.key === "order_date" ? (
                        <button type="button" className="inline-flex items-center gap-1" onClick={() => setSort(sort === "date_desc" ? "date_asc" : "date_desc")}>
                          {c.label} {sort === "date_desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />}
                        </button>
                      ) : c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.length > 0 && <tr style={{ height: items[0].start }} />}
                {items.map((it) => {
                  const r = rows[it.index];
                  return (
                    <tr key={String(r.order_id)} className="cursor-pointer border-t border-slate-100 hover:bg-brand-50/50" style={{ height: ROW_H }} onClick={() => setOpen(String(r.order_id))}>
                      {columns.map((c) => (
                        <td key={c.key} className={cn("table-cell", ["money", "int", "pct"].includes(c.kind) && "text-right tabular-nums")}>
                          {c.key === "order_status" ? (
                            <span className="inline-flex items-center gap-1.5">
                              <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLORS[String(r.order_status)] }} />
                              {String(r.order_status)}
                            </span>
                          ) : c.key === "customer_id" && String(r.customer_id).startsWith("C-") ? (
                            <Badge tone="amber">{String(r.customer_id)}</Badge>
                          ) : (
                            formatField(c.kind, r[c.key])
                          )}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                {items.length > 0 && <tr style={{ height: v.getTotalSize() - items[items.length - 1].end }} />}
              </tbody>
            </table>
            {iq.isLoading && <Loading />}
            {!iq.isLoading && rows.length === 0 && <p className="p-6 text-center text-sm text-slate-400">No orders match.</p>}
            {iq.isFetchingNextPage && <Loading label="Loading more…" className="min-h-[40px]" />}
          </div>
        </div>
      )}
      <OrderDrawer orderId={open} onClose={() => setOpen(null)} />
    </div>
  );
}
