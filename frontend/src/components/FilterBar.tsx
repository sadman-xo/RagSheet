import { useMemo, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown, ChevronRight, RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import { useCatalog } from "@/api/hooks";
import type { Catalog } from "@/api/types";
import { LABELS, useFilters, type ListKey, type UiFilters } from "@/state/filters";
import { useAuth } from "@/auth/AuthProvider";
import { LockedChip, Segmented } from "./ui";
import { cn } from "@/lib/cn";

function optionsFor(key: ListKey, cat: Catalog, f: UiFilters): string[] {
  switch (key) {
    case "regions":
      return cat.regions.map((r) => r.name);
    case "countries":
      return cat.regions.filter((r) => !f.regions.length || f.regions.includes(r.name)).flatMap((r) => r.countries);
    case "categories":
      return cat.categories.map((c) => c.name);
    case "sub_categories":
      return cat.categories.filter((c) => !f.categories.length || f.categories.includes(c.name)).flatMap((c) => c.sub_categories.map((s) => s.name));
    case "products":
      return cat.categories
        .filter((c) => !f.categories.length || f.categories.includes(c.name))
        .flatMap((c) => c.sub_categories)
        .filter((s) => !f.sub_categories.length || f.sub_categories.includes(s.name))
        .flatMap((s) => s.products);
    default:
      return (cat as unknown as Record<string, string[]>)[key] ?? [];
  }
}

export function MultiSelect({ label, options, value, onToggle, onClear, testId }: {
  label: string;
  options: string[];
  value: string[];
  onToggle: (v: string) => void;
  onClear: () => void;
  testId?: string;
}) {
  const [q, setQ] = useState("");
  const shown = options.filter((o) => o.toLowerCase().includes(q.toLowerCase()));
  const text = value.length === 0 ? "All" : value.length === 1 ? value[0] : `${value.length} selected`;
  return (
    <Popover.Root>
      <Popover.Trigger
        data-testid={testId}
        className={cn(
          "inline-flex h-7 max-w-[220px] items-center gap-1 rounded-md border px-2.5 text-xs transition",
          value.length ? "border-slate-800 bg-slate-800 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900",
        )}
      >
        <span className={value.length ? "text-slate-300" : "text-slate-500"}>{label}</span>
        <span className="truncate font-medium">{text}</span>
        <ChevronDown className="h-3 w-3 shrink-0 opacity-60" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={4} className="menu w-64 p-1.5">
          {options.length > 8 && (
            <div className="relative mb-2">
              <Search className="absolute left-2 top-[7px] h-3.5 w-3.5 text-slate-400" />
              <input className="input py-1 pl-7 text-xs" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          )}
          <div className="scrollbar-thin max-h-64 overflow-y-auto">
            {shown.map((o) => (
              <button key={o} type="button" onClick={() => onToggle(o)} className="menu-item py-1">
                <span className={cn("flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border", value.includes(o) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white")}>
                  {value.includes(o) && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
                </span>
                <span className="truncate">{o}</span>
              </button>
            ))}
            {shown.length === 0 && <p className="px-2 py-1 text-xs text-slate-400">No match</p>}
          </div>
          {value.length > 0 && (
            <button type="button" className="btn-ghost mt-1 w-full text-xs" onClick={onClear}>
              Clear
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function PeriodSelect() {
  const { f, set } = useFilters();
  const cat = useCatalog();
  if (!cat.data) return null;
  return (
    <div className="flex items-center gap-1">
      <select
        className="h-7 rounded-md border border-slate-200 bg-white px-2 text-xs font-medium text-slate-800 hover:border-slate-400"
        value={f.period}
        onChange={(e) => set({ period: e.target.value, from: f.from ?? cat.data.date_range.min, to: f.to ?? cat.data.date_range.max })}
        data-testid="period-select"
        aria-label="Period"
      >
        {cat.data.periods.map((p) => (
          <option key={p.id} value={p.id}>{p.label}</option>
        ))}
        <optgroup label="Year">
          {cat.data.years.map((y) => (
            <option key={y} value={`y${y}`}>{y}</option>
          ))}
        </optgroup>
        <optgroup label="Quarter">
          {cat.data.years.flatMap((y) => [1, 2, 3, 4].map((q) => (
            <option key={`${y}q${q}`} value={`y${y}q${q}`}>Q{q} {y}</option>
          )))}
        </optgroup>
        <option value="custom">Custom…</option>
      </select>
      {f.period === "custom" && (
        <>
          <input type="date" className="h-7 rounded-md border border-slate-200 bg-white px-1.5 text-xs" value={f.from ?? ""} min={cat.data.date_range.min} max={cat.data.date_range.max} onChange={(e) => set({ from: e.target.value })} />
          <span className="text-xs text-slate-400">–</span>
          <input type="date" className="h-7 rounded-md border border-slate-200 bg-white px-1.5 text-xs" value={f.to ?? ""} min={cat.data.date_range.min} max={cat.data.date_range.max} onChange={(e) => set({ to: e.target.value })} />
        </>
      )}
    </div>
  );
}

const PRIMARY: ListKey[] = ["regions", "countries", "categories", "sub_categories", "products"];
const SECONDARY: ListKey[] = ["segments", "genders", "statuses", "shipping_methods", "payment_methods", "discount_bands"];

export function FilterBar({ hide = [] }: { hide?: ListKey[] }) {
  const { f, set, toggle, reset, activeCount } = useFilters();
  const cat = useCatalog();
  const { me } = useAuth();
  const [more, setMore] = useState(false);
  const locked = me?.scope.locked_filters ?? {};
  if (!cat.data) return <div className="h-9" />;
  const keys = (list: ListKey[]) => list.filter((k) => !hide.includes(k) && !(k in locked));
  return (
    <div className="sticky top-0 z-20 -mx-4 mb-5 border-b border-slate-200 bg-slate-50/95 px-4 py-2.5 backdrop-blur lg:-mx-8 lg:px-8" data-testid="filter-bar">
      <div className="flex flex-wrap items-center gap-1.5">
        <PeriodSelect />
        <span className="mx-1 h-4 w-px bg-slate-300" aria-hidden />
        {Object.entries(locked).map(([k, v]) => (
          <LockedChip key={k} label={`${k === "regions" ? "Region" : "Category"}: ${(v as string[]).join(", ")}`} />
        ))}
        {keys(PRIMARY).map((k) => (
          <MultiSelect key={k} label={LABELS[k]} options={optionsFor(k, cat.data, f)} value={f[k]} onToggle={(v) => toggle(k, v)} onClear={() => set({ [k]: [] })} testId={`filter-${k}`} />
        ))}
        <button type="button" className={cn("btn-ghost h-7 text-xs", more && "bg-slate-200 text-slate-900")} onClick={() => setMore(!more)}>
          <SlidersHorizontal className="h-3.5 w-3.5" /> More
        </button>
        <div className="ml-auto flex items-center gap-2">
          <Segmented value={f.revenue} onChange={(v) => set({ revenue: v })} options={[{ value: "gross", label: "Gross" }, { value: "net", label: "Net" }]} size="xs" />
          {activeCount > 0 && (
            <button type="button" className="btn-ghost text-xs" onClick={reset} data-testid="filter-reset">
              <RotateCcw className="h-3.5 w-3.5" /> Reset
            </button>
          )}
        </div>
      </div>
      {more && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {keys(SECONDARY).map((k) => (
            <MultiSelect key={k} label={LABELS[k]} options={optionsFor(k, cat.data, f)} value={f[k]} onToggle={(v) => toggle(k, v)} onClear={() => set({ [k]: [] })} />
          ))}
        </div>
      )}
      <Breadcrumbs />
    </div>
  );
}

/** Drill path: All › Europe › Germany › Laptops */
export function Breadcrumbs() {
  const { f, set } = useFilters();
  const crumbs = useMemo(() => {
    const out: { label: string; clear: Partial<UiFilters> }[] = [];
    const levels: [ListKey, ListKey[]][] = [
      ["regions", ["countries", "categories", "sub_categories", "products"]],
      ["countries", ["categories", "sub_categories", "products"]],
      ["categories", ["sub_categories", "products"]],
      ["sub_categories", ["products"]],
      ["products", []],
    ];
    for (const [k, below] of levels) {
      if (f[k].length === 1) out.push({ label: f[k][0], clear: Object.fromEntries(below.map((b) => [b, []])) });
    }
    return out;
  }, [f]);
  if (!crumbs.length) return null;
  return (
    <nav className="mt-2 flex items-center gap-1 text-xs text-slate-500" aria-label="Drill path" data-testid="breadcrumbs">
      <button type="button" className="hover:text-slate-900 hover:underline" onClick={() => set({ regions: [], countries: [], categories: [], sub_categories: [], products: [] })}>
        All
      </button>
      {crumbs.map((c, i) => (
        <span key={c.label} className="flex items-center gap-1">
          <ChevronRight className="h-3 w-3" />
          {i < crumbs.length - 1 ? (
            <button type="button" className="hover:text-slate-900 hover:underline" onClick={() => set(c.clear)}>
              {c.label}
            </button>
          ) : (
            <span className="font-medium text-slate-700">{c.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
