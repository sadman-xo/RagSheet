import { useRef, useState } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart, TreemapChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { Download, Image, List, MoreHorizontal } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import { saveBlob } from "@/api/client";
import { BASELINE, FONT, GRID_LINE, INK, INK_2, MUTED, PALETTE } from "@/lib/colors";

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, TreemapChart, HeatmapChart, BoxplotChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent, MarkAreaComponent,
  CanvasRenderer,
]);

// One theme for every chart: app font, quiet tooltip, recessive zoom slider.
echarts.registerTheme("panorama", {
  color: PALETTE,
  textStyle: { fontFamily: FONT, color: INK_2 },
  tooltip: {
    backgroundColor: "#ffffff",
    borderColor: "#e4e2dc",
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: INK, fontSize: 12, fontFamily: FONT },
    extraCssText: "border-radius:6px;box-shadow:0 8px 24px -8px rgba(27,26,24,.18);",
    axisPointer: { lineStyle: { color: BASELINE }, shadowStyle: { color: "rgba(27,26,24,0.04)" } },
  },
  legend: { textStyle: { color: INK_2 } },
  dataZoom: [{
    borderColor: "transparent",
    backgroundColor: "#f7f6f3",
    fillerColor: "rgba(42,120,214,0.10)",
    dataBackground: { lineStyle: { color: BASELINE }, areaStyle: { color: GRID_LINE } },
    selectedDataBackground: { lineStyle: { color: "#86b6ef" }, areaStyle: { color: "rgba(42,120,214,0.12)" } },
    handleStyle: { color: "#ffffff", borderColor: MUTED },
    moveHandleStyle: { color: BASELINE },
    textStyle: { color: MUTED, fontSize: 10 },
  }],
});

export interface ChartClick {
  name: string;
  seriesName?: string;
  value?: unknown;
  data?: unknown;
}

export function Chart({ option, height = 280, onClick, testId }: {
  option: EChartsOption;
  height?: number | string;
  onClick?: (p: ChartClick) => void;
  testId?: string;
}) {
  return (
    <div data-testid={testId} style={{ height }}>
      <ReactEChartsCore
        echarts={echarts}
        theme="panorama"
        option={option}
        notMerge
        lazyUpdate
        style={{ height: "100%", width: "100%" }}
        onEvents={onClick ? { click: (p: ChartClick) => onClick(p) } : undefined}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

/** Chart with the standard menu: View orders, Save PNG, Download data. */
export function ChartWithMenu({ option, height, onClick, rows, name, onViewOrders, testId }: {
  option: EChartsOption;
  height?: number | string;
  onClick?: (p: ChartClick) => void;
  rows?: Record<string, unknown>[];
  name: string;
  onViewOrders?: () => void;
  testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref} className="relative">
      <div className="absolute -top-9 right-0 z-10">
        <ChartMenu
          name={name}
          rows={rows}
          onViewOrders={onViewOrders}
          getCanvas={() => ref.current?.querySelector("canvas") ?? null}
        />
      </div>
      <Chart option={option} height={height} onClick={onClick} testId={testId} />
    </div>
  );
}

export function ChartMenu({ name, rows, onViewOrders, getCanvas }: {
  name: string;
  rows?: Record<string, unknown>[];
  onViewOrders?: () => void;
  getCanvas: () => HTMLCanvasElement | null;
}) {
  const [open, setOpen] = useState(false);
  const file = name.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className="btn-ghost px-1.5 text-slate-400 hover:text-slate-800" aria-label="Chart menu">
        <MoreHorizontal className="h-4 w-4" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={4} className="menu w-44">
          {onViewOrders && (
            <button className="menu-item" onClick={() => { setOpen(false); onViewOrders(); }}>
              <List className="h-3.5 w-3.5" /> View orders
            </button>
          )}
          <button
            className="menu-item"
            onClick={() => {
              const c = getCanvas();
              if (c) c.toBlob((b) => b && saveBlob(b, `${file}.png`));
              setOpen(false);
            }}
          >
            <Image className="h-3.5 w-3.5" /> Save PNG
          </button>
          {rows && (
            <button
              className="menu-item"
              onClick={() => {
                saveBlob(new Blob([toCsv(rows)], { type: "text/csv" }), `${file}.csv`);
                setOpen(false);
              }}
            >
              <Download className="h-3.5 w-3.5" /> Download data
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]).filter((k) => !k.endsWith("__n"));
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return "";
    let s = String(v);
    if (/^[=+\-@\t\r]/.test(s) && Number.isNaN(Number(s))) s = "'" + s;
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [keys.join(","), ...rows.map((r) => keys.map((k) => esc(r[k])).join(","))].join("\n");
}
