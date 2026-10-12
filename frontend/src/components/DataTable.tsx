import { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import type { ColumnMeta, Row } from "@/api/types";
import { byKind } from "@/lib/format";
import { cn } from "@/lib/cn";

/** Client-side table for query results (max 500 rows). Rate values with n < 30 are grey. */
export function ResultTable({ columns, rows, totals, maxHeight = 360, onRowClick, compact }: {
  columns: ColumnMeta[];
  rows: Row[];
  totals?: Row | null;
  maxHeight?: number;
  onRowClick?: (r: Row) => void;
  compact?: boolean;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const hasPrior = rows.length > 0 && columns.some((c) => c.role === "metric" && `${c.key}__prior` in rows[0]);
  const defs = useMemo<ColumnDef<Row>[]>(() => {
    const out: ColumnDef<Row>[] = [];
    for (const c of columns) {
      out.push({
        id: c.key,
        accessorFn: (r) => r[c.key],
        header: c.label,
        cell: (info) => {
          const v = info.getValue() as number | string | null;
          if (c.role === "dim") return <span className="text-slate-900">{String(v ?? "–")}</span>;
          const n = info.row.original[`${c.key}__n`] as number | undefined;
          return <span className={cn("num text-[12.5px]", n !== undefined && n !== null && n < 30 && "text-slate-400")}>{byKind(c.kind, v as number)}</span>;
        },
        meta: { align: c.role === "metric" ? "right" : "left" },
      });
      if (hasPrior && c.role === "metric") {
        out.push({
          id: `${c.key}__chg`,
          accessorFn: (r) => (c.kind === "pct" ? r[`${c.key}__delta`] : r[`${c.key}__pct`]),
          header: "Δ vs prior",
          cell: (info) => {
            const v = info.getValue() as number | null;
            if (v === null || v === undefined) return "–";
            const good = c.higher_is_better === null || c.higher_is_better === undefined ? null : (v >= 0) === c.higher_is_better;
            return (
              <span className={cn("num text-xs", good === null ? "text-slate-500" : good ? "text-emerald-700" : "text-red-700")}>
                {v >= 0 ? "+" : ""}{v.toFixed(c.kind === "pct" ? 2 : 1)}{c.kind === "pct" ? " pts" : "%"}
              </span>
            );
          },
          meta: { align: "right" },
        });
      }
    }
    return out;
  }, [columns, hasPrior]);

  const table = useReactTable({ data: rows, columns: defs, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });

  return (
    <div className="scrollbar-thin overflow-auto rounded border border-slate-200" style={{ maxHeight }}>
      <table className="w-full border-collapse">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const align = (h.column.columnDef.meta as { align?: string })?.align;
                const sorted = h.column.getIsSorted();
                return (
                  <th key={h.id} className={cn("table-head cursor-pointer select-none hover:text-slate-900", align === "right" && "text-right")} onClick={h.column.getToggleSortingHandler()}>
                    <span className="inline-flex items-center gap-1">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {sorted === "asc" && <ArrowUp className="h-3 w-3" />}
                      {sorted === "desc" && <ArrowDown className="h-3 w-3" />}
                    </span>
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.id} className={cn("border-t border-slate-100 first:border-t-0 hover:bg-slate-50", onRowClick && "cursor-pointer")} onClick={() => onRowClick?.(r.original)}>
              {r.getVisibleCells().map((cell) => {
                const align = (cell.column.columnDef.meta as { align?: string })?.align;
                return (
                  <td key={cell.id} className={cn("table-cell", compact && "py-1", align === "right" && "text-right")}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
          {totals && rows.length > 1 && (
            <tr className="sticky bottom-0 border-t border-slate-300 bg-slate-50 font-semibold">
              {table.getVisibleLeafColumns().map((col, i) => {
                const c = columns.find((x) => x.key === col.id);
                const v = c ? totals[c.key] : null;
                return (
                  <td key={col.id} className={cn("table-cell", c?.role === "metric" && "text-right")}>
                    {i === 0 ? "Total" : c?.role === "metric" ? byKind(c.kind, v as number) : ""}
                  </td>
                );
              })}
            </tr>
          )}
        </tbody>
      </table>
      {rows.length === 0 && <p className="p-4 text-center text-sm text-slate-400">No rows.</p>}
    </div>
  );
}
