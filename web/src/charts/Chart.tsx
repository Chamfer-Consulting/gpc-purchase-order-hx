import { useCallback, useMemo, useRef } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useComputedColorScheme } from "@mantine/core";
import { echarts, type EChartsOption } from "./echartsCore";
import { registerChartThemes, themeNameFor } from "./theme";
import { FONT_FAMILY } from "./palette";
import { EmptyState } from "@/components/EmptyState";

registerChartThemes();

interface ChartProps {
  option: EChartsOption;
  /** true when the caller has no data — renders a tidy empty state instead. */
  empty?: boolean;
  emptyLabel?: string;
  height?: number | string;
  /** merged onto every option: consistent animation + no toolbox clutter. */
  className?: string;
  onEvents?: Record<string, (params: unknown) => void>;
}

const BASE: EChartsOption = {
  animationDuration: 300,
  animationEasing: "cubicOut",
  textStyle: { fontFamily: FONT_FAMILY },
};

type EC = ReturnType<typeof echarts.init>;
type LineSeries = { i: number; data: unknown[] };

/** value of a line series at (or nearest to) the x the cursor is over */
function seriesYAt(data: unknown[], xData: number): number | null {
  if (data.length === 0) return null;
  if (Array.isArray(data[0])) {
    // time axis: data is [x, y] pairs, x an ISO string or epoch ms
    let bestY: number | null = null;
    let bestDx = Infinity;
    for (const p of data as [string | number, number | null][]) {
      const px = typeof p[0] === "string" ? Date.parse(p[0]) : Number(p[0]);
      const dx = Math.abs(px - xData);
      if (dx < bestDx && p[1] != null) {
        bestDx = dx;
        bestY = Number(p[1]);
      }
    }
    return bestY;
  }
  const v = (data as (number | null)[])[Math.round(xData)];
  return v == null ? null : Number(v);
}

/**
 * Dim every tooltip row except the line the pointer is nearest to (in data space
 * — value axes are linear, so nearest-in-value is nearest-on-screen). Works on
 * the already-rendered tooltip DOM (`[data-si]` rows the formatter emits) rather
 * than through the formatter, so it can't fall out of step with the axis pointer
 * and it holds while the mouse is still.
 */
function attachPointerTracker(inst: EC, linesRef: React.MutableRefObject<LineSeries[]>) {
  const zr = inst.getZr();

  const paint = (best: number) => {
    const rows = inst.getDom().querySelectorAll<HTMLElement>("[data-si]");
    rows.forEach((el) => {
      const si = el.dataset.si;
      el.style.opacity = best < 0 || si === "" || Number(si) === best ? "1" : "0.4";
    });
  };

  const onMove = (ev: { offsetX: number; offsetY: number }) => {
    const lines = linesRef.current;
    if (lines.length < 2 || !inst.containPixel({ gridIndex: 0 }, [ev.offsetX, ev.offsetY])) {
      paint(-1);
      return;
    }
    const conv = inst.convertFromPixel({ gridIndex: 0 }, [ev.offsetX, ev.offsetY]) as
      | number[]
      | undefined;
    if (!conv) {
      paint(-1);
      return;
    }
    const [xData, yCursor] = conv;
    let best = -1;
    let bestDy = Infinity;
    for (const { i, data } of lines) {
      const y = seriesYAt(data, xData);
      if (y == null || Number.isNaN(y)) continue;
      const dy = Math.abs(y - yCursor);
      if (dy < bestDy) {
        bestDy = dy;
        best = i;
      }
    }
    paint(best);
  };
  zr.on("mousemove", onMove);
  zr.on("globalout", () => paint(-1));
}

/**
 * The one chart component. Give it a plain ECharts `option`; it applies the house
 * theme for the active colour scheme, keeps a sensible base, and resizes with its
 * container. Data shaping stays in the caller / the backend.
 */
export function Chart({
  option,
  empty,
  emptyLabel = "No data in range",
  height = 300,
  className,
  onEvents,
}: ChartProps) {
  const scheme = useComputedColorScheme("light");
  const merged = useMemo<EChartsOption>(() => ({ ...BASE, ...option }), [option]);

  // line series (index + raw data) for the pointer tracker — refreshed each
  // render, read by the zrender listener attached once in onChartReady.
  const linesRef = useRef<LineSeries[]>([]);
  linesRef.current = useMemo(() => {
    const raw = (merged as { series?: unknown }).series;
    const arr = Array.isArray(raw) ? (raw as { type?: string; data?: unknown[] }[]) : [];
    const out: LineSeries[] = [];
    arr.forEach((s, i) => {
      if (s.type === "line" && Array.isArray(s.data) && s.data.length) out.push({ i, data: s.data });
    });
    return out;
  }, [merged]);

  // echarts-for-react types the instance from its own bundled echarts; same
  // object at runtime, so bridge it here.
  const onChartReady = useCallback(
    (inst: unknown) => attachPointerTracker(inst as EC, linesRef),
    [],
  );

  if (empty) {
    return <EmptyState label={emptyLabel} height={height} />;
  }

  return (
    <ReactEChartsCore
      echarts={echarts}
      theme={themeNameFor(scheme)}
      option={merged}
      notMerge
      lazyUpdate
      onChartReady={onChartReady}
      style={{ height, width: "100%" }}
      className={className}
      onEvents={onEvents}
    />
  );
}
