import type { EChartsOption } from "echarts";
import { axisFormatter, byKind } from "@/lib/format";
import { BASELINE, colorFor, GRID_LINE, INK_2, MUTED, NEGATIVE, PALETTE, POSITIVE, SERIES } from "@/lib/colors";

const GRID = { left: 4, right: 12, top: 28, bottom: 4, containLabel: true };
const AXIS_LABEL = { color: MUTED, fontSize: 11 };
const SPLIT = { lineStyle: { color: GRID_LINE } };
const AXIS_LINE = { lineStyle: { color: BASELINE } };
const LEGEND = { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, itemGap: 14, textStyle: { fontSize: 11.5, color: INK_2 } };

export interface SeriesDef {
  name: string;
  data: (number | null)[];
  color?: string;
  dashed?: boolean;
  area?: boolean;
  kind?: string;
  yAxis?: 0 | 1;
  type?: "line" | "bar";
  stack?: string;
}

function tooltipFmt(kinds: Record<string, string>, fallback: string) {
  return (params: unknown) => {
    const ps = (Array.isArray(params) ? params : [params]) as { axisValueLabel?: string; name?: string; seriesName: string; value: unknown; marker: string }[];
    if (!ps.length) return "";
    const head = ps[0].axisValueLabel ?? ps[0].name ?? "";
    const lines = ps.map((p) => {
      const v = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value;
      return `${p.marker} ${p.seriesName}: <b>${byKind(kinds[p.seriesName] ?? fallback, v as number)}</b>`;
    });
    return [head, ...lines].join("<br/>");
  };
}

export function lineOption(x: string[], series: SeriesDef[], kind: string, opts: { kind2?: string; legend?: boolean; zoom?: boolean } = {}): EChartsOption {
  const kinds = Object.fromEntries(series.map((s) => [s.name, s.kind ?? (s.yAxis === 1 ? opts.kind2 ?? kind : kind)]));
  const yAxes: EChartsOption["yAxis"] = [
    { type: "value", axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(kind) }, splitLine: SPLIT },
  ];
  if (opts.kind2) (yAxes as object[]).push({ type: "value", axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(opts.kind2) }, splitLine: { show: false } });
  return {
    color: PALETTE,
    grid: { ...GRID, top: opts.legend === false ? 12 : 32, bottom: opts.zoom ? 36 : 8 },
    tooltip: { trigger: "axis", formatter: tooltipFmt(kinds, kind) },
    legend: opts.legend === false ? undefined : LEGEND,
    xAxis: { type: "category", data: x, axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, axisTick: { show: false }, boundaryGap: series.some((s) => s.type === "bar") },
    yAxis: yAxes,
    dataZoom: opts.zoom ? [{ type: "slider", height: 16, bottom: 4 }] : undefined,
    series: series.map((s, i) => ({
      name: s.name,
      type: s.type ?? "line",
      data: s.data,
      yAxisIndex: s.yAxis ?? 0,
      stack: s.stack,
      smooth: s.type === "bar" ? undefined : 0.2,
      showSymbol: false,
      connectNulls: false,
      itemStyle: { color: s.color ?? PALETTE[i % PALETTE.length] },
      lineStyle: s.type === "bar" ? undefined : { width: 2, type: s.dashed ? "dashed" : "solid" },
      areaStyle: s.area ? { opacity: 0.12 } : undefined,
    })),
  } as EChartsOption;
}

export function barOption(categories: string[], series: SeriesDef[], kind: string, opts: {
  horizontal?: boolean; stack?: boolean; legend?: boolean; kind2?: string; colorByCategory?: boolean; percent?: boolean;
} = {}): EChartsOption {
  const kinds = Object.fromEntries(series.map((s) => [s.name, s.kind ?? (s.yAxis === 1 ? opts.kind2 ?? kind : kind)]));
  const valueAxis = { type: "value" as const, axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(opts.percent ? "pct" : kind) }, splitLine: SPLIT, max: opts.percent ? 100 : undefined };
  const catAxis = {
    type: "category" as const, data: categories, axisLabel: { ...AXIS_LABEL, width: 110, overflow: "truncate" as const },
    axisLine: AXIS_LINE, axisTick: { show: false }, inverse: opts.horizontal,
  };
  const yAxes: object[] = [valueAxis];
  if (opts.kind2 && !opts.horizontal) yAxes.push({ type: "value", axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(opts.kind2) }, splitLine: { show: false } });
  const showLegend = opts.legend ?? series.length > 1;
  return {
    color: PALETTE,
    grid: { ...GRID, top: showLegend ? 32 : 12 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: tooltipFmt(kinds, kind) },
    legend: showLegend ? LEGEND : undefined,
    xAxis: opts.horizontal ? valueAxis : catAxis,
    yAxis: opts.horizontal ? catAxis : yAxes,
    series: series.map((s, i) => ({
      name: s.name,
      type: s.type ?? "bar",
      data: s.type === "line" ? s.data : s.data.map((v, j) => ({ value: v, itemStyle: opts.colorByCategory ? { color: colorFor(categories[j], j) } : undefined })),
      stack: opts.stack ? "total" : s.stack,
      yAxisIndex: s.yAxis ?? 0,
      barMaxWidth: 24,
      barGap: "12%",
      itemStyle: { color: s.color ?? colorFor(s.name, i), borderRadius: opts.stack ? 0 : opts.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0], borderColor: opts.stack ? "#fff" : undefined, borderWidth: opts.stack ? 1 : 0 },
      symbol: "circle",
      symbolSize: 7,
      lineStyle: s.type === "line" ? { width: 2 } : undefined,
    })),
  } as EChartsOption;
}

export interface TreeNode {
  name: string;
  value: number;
  children?: TreeNode[];
}

export function treemapOption(data: TreeNode[], kind: string): EChartsOption {
  return {
    color: PALETTE,
    tooltip: { formatter: (p: unknown) => {
      const x = p as { treePathInfo: { name: string }[]; value: number };
      return `${x.treePathInfo.map((t) => t.name).filter(Boolean).join(" › ")}<br/><b>${byKind(kind, x.value)}</b>`;
    } },
    series: [{
      type: "treemap", data, roam: false, nodeClick: false, breadcrumb: { show: false }, width: "100%", height: "100%",
      upperLabel: { show: true, height: 20, color: "#fff", fontSize: 11, fontWeight: 500 },
      label: { fontSize: 11, formatter: (p: unknown) => { const x = p as { name: string; value: number }; return `${x.name}\n${byKind(kind, x.value, true)}`; } },
      levels: [
        { itemStyle: { borderColor: "#fff", borderWidth: 2, gapWidth: 2, borderRadius: 2 } },
        { colorSaturation: [0.35, 0.6], itemStyle: { borderColor: "rgba(255,255,255,.55)", gapWidth: 1, borderWidth: 1 } },
      ],
    }],
  } as EChartsOption;
}

export function heatmapOption(xs: string[], ys: string[], data: [number, number, number | null][], kind: string, opts: { reverse?: boolean } = {}): EChartsOption {
  const vals = data.map((d) => d[2]).filter((v): v is number => v !== null);
  const min = vals.length ? Math.min(...vals) : 0;
  const max = vals.length ? Math.max(...vals) : 1;
  return {
    grid: { ...GRID, top: 8, bottom: 40 },
    tooltip: { formatter: (p: unknown) => {
      const x = p as { value: [number, number, number] };
      return `${ys[x.value[1]]} · ${xs[x.value[0]]}<br/><b>${byKind(kind, x.value[2])}</b>`;
    } },
    xAxis: { type: "category", data: xs, axisLabel: { ...AXIS_LABEL, rotate: xs.length > 8 ? 35 : 0 }, splitArea: { show: true } },
    yAxis: { type: "category", data: ys, axisLabel: { ...AXIS_LABEL, width: 110, overflow: "truncate" }, splitArea: { show: true } },
    visualMap: {
      min, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, itemWidth: 10,
      textStyle: { fontSize: 10 }, formatter: (v: unknown) => byKind(kind, v as number, true),
      inRange: { color: opts.reverse ? ["#256abf", "#f0efec", "#d03b3b"] : ["#dbe8fa", "#6da7ec", "#184f95"] },
    },
    series: [{ type: "heatmap", data, label: { show: xs.length * ys.length <= 60, fontSize: 10, formatter: (p: unknown) => byKind(kind, (p as { value: number[] }).value[2], true) } }],
  } as EChartsOption;
}

export function scatterOption(points: { name: string; x: number; y: number; size?: number; group?: string }[], xKind: string, yKind: string, xName: string, yName: string): EChartsOption {
  const groups = [...new Set(points.map((p) => p.group ?? "All"))];
  const maxSize = Math.max(1, ...points.map((p) => p.size ?? 1));
  return {
    color: PALETTE,
    grid: { ...GRID, top: groups.length > 1 ? 32 : 16, left: 16, bottom: 24 },
    legend: groups.length > 1 ? LEGEND : undefined,
    tooltip: { formatter: (p: unknown) => {
      const x = p as { data: { name: string; value: [number, number] } };
      return `<b>${x.data.name}</b><br/>${xName}: ${byKind(xKind, x.data.value[0])}<br/>${yName}: ${byKind(yKind, x.data.value[1])}`;
    } },
    xAxis: { type: "value", name: xName, nameLocation: "middle", nameGap: 26, axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(xKind) }, splitLine: SPLIT, scale: true },
    yAxis: { type: "value", name: yName, axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(yKind) }, splitLine: SPLIT, scale: true },
    series: groups.map((g) => ({
      name: g, type: "scatter",
      data: points.filter((p) => (p.group ?? "All") === g).map((p) => ({ name: p.name, value: [p.x, p.y], symbolSize: 8 + 22 * Math.sqrt((p.size ?? 1) / maxSize) })),
      itemStyle: { opacity: 0.85, borderColor: "#fff", borderWidth: 1 },
    })),
  } as EChartsOption;
}

export function boxplotOption(groups: { group: string; min: number; q1: number; median: number; q3: number; max: number; n: number }[], kind: string): EChartsOption {
  return {
    grid: { ...GRID, top: 12 },
    tooltip: { formatter: (p: unknown) => {
      const x = p as { name: string; data: number[] };
      const g = groups.find((y) => y.group === x.name);
      return `<b>${x.name}</b> (n=${g?.n})<br/>max ${byKind(kind, g?.max)}<br/>Q3 ${byKind(kind, g?.q3)}<br/>median ${byKind(kind, g?.median)}<br/>Q1 ${byKind(kind, g?.q1)}<br/>min ${byKind(kind, g?.min)}`;
    } },
    xAxis: { type: "category", data: groups.map((g) => g.group), axisLabel: AXIS_LABEL },
    yAxis: { type: "value", axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(kind) }, splitLine: SPLIT },
    series: [{ type: "boxplot", data: groups.map((g) => [g.min, g.q1, g.median, g.q3, g.max]), itemStyle: { color: "#dbe8fa", borderColor: SERIES.blue, borderWidth: 1.5 } }],
  } as EChartsOption;
}

export function waterfallOption(steps: { label: string; value: number; total?: boolean }[], kind: string): EChartsOption {
  const base: number[] = [];
  const pos: (number | string)[] = [];
  const neg: (number | string)[] = [];
  const tot: (number | string)[] = [];
  let running = 0;
  for (const s of steps) {
    if (s.total) {
      base.push(0); tot.push(s.value); pos.push("-"); neg.push("-");
      running = s.value;
    } else if (s.value >= 0) {
      base.push(running); pos.push(s.value); neg.push("-"); tot.push("-");
      running += s.value;
    } else {
      running += s.value;
      base.push(running); neg.push(-s.value); pos.push("-"); tot.push("-");
    }
  }
  return {
    grid: { ...GRID, top: 12 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p: unknown) => {
      const ps = p as { dataIndex: number }[];
      const s = steps[ps[0].dataIndex];
      return `${s.label}<br/><b>${byKind(kind, s.value)}</b>`;
    } },
    xAxis: { type: "category", data: steps.map((s) => s.label), axisLabel: { ...AXIS_LABEL, interval: 0 } },
    yAxis: { type: "value", axisLabel: { ...AXIS_LABEL, formatter: axisFormatter(kind) }, splitLine: SPLIT },
    series: [
      { type: "bar", stack: "w", data: base, itemStyle: { color: "transparent" }, emphasis: { disabled: true } },
      { type: "bar", stack: "w", data: tot, itemStyle: { color: SERIES.blue, borderRadius: 2 }, barMaxWidth: 40 },
      { type: "bar", stack: "w", data: pos, itemStyle: { color: POSITIVE, borderRadius: 2 }, barMaxWidth: 40 },
      { type: "bar", stack: "w", data: neg, itemStyle: { color: NEGATIVE, borderRadius: 2 }, barMaxWidth: 40 },
    ],
  } as EChartsOption;
}

export function donutOption(items: { name: string; value: number }[], kind: string): EChartsOption {
  return {
    tooltip: { formatter: (p: unknown) => { const x = p as { name: string; value: number; percent: number }; return `${x.name}: <b>${byKind(kind, x.value)}</b> (${x.percent}%)`; } },
    legend: { ...LEGEND, orient: "vertical", left: undefined, right: 0, top: "middle" },
    series: [{
      type: "pie", radius: ["56%", "78%"], center: ["35%", "50%"], avoidLabelOverlap: true, label: { show: false }, padAngle: 1, itemStyle: { borderRadius: 2 },
      data: items.map((it, i) => ({ ...it, itemStyle: { color: colorFor(it.name, i) } })),
    }],
  } as EChartsOption;
}

export function sparkOption(values: (number | null)[], color: string): EChartsOption {
  return {
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: "category", show: false, data: values.map((_, i) => i) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [{ type: "line", data: values, showSymbol: false, smooth: 0.3, lineStyle: { width: 1.5, color }, areaStyle: { color, opacity: 0.1 } }],
  } as EChartsOption;
}
