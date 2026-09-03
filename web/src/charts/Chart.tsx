import { useCallback, useEffect, useMemo, useRef } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useComputedColorScheme } from "@mantine/core";
import { echarts, type EChartsOption } from "./echartsCore";
import { setHoveredSeries } from "./options";
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
/** one trackable line: series index + x/y already reduced to plain numbers
 *  (dates parsed to epoch ms once) so the pointer tracker never re-parses. */
type LineSeries = { i: number; xs: number[]; ys: (number | null)[] };

/** line series worth tracking for hover emphasis: real data lines with points,
 *  minus any the option builder flagged `__track: false` (ghost / reference /
 *  trend overlays). x is parsed to a number here, not on every pointer move. */
function deriveLines(merged: EChartsOption): LineSeries[] {
  const raw = (merged as { series?: unknown }).series;
  const arr = Array.isArray(raw)
    ? (raw as { type?: string; data?: unknown[]; __track?: boolean }[])
    : [];
  const out: LineSeries[] = [];
  arr.forEach((s, i) => {
    if (s.type !== "line" || !Array.isArray(s.data) || !s.data.length) return;
    if (s.__track === false) return;
    const xs: number[] = [];
    const ys: (number | null)[] = [];
    if (Array.isArray(s.data[0])) {
      // time axis: [x, y] pairs, x an ISO string or epoch ms
      for (const p of s.data as [string | number, number | null][]) {
        xs.push(typeof p[0] === "string" ? Date.parse(p[0]) : Number(p[0]));
        ys.push(p[1] == null ? null : Number(p[1]));
      }
    } else {
      // category axis: y values, index-aligned to the shared x categories
      (s.data as (number | null)[]).forEach((v, k) => {
        xs.push(k);
        ys.push(v == null ? null : Number(v));
      });
    }
    out.push({ i, xs, ys });
  });
  return out;
}

/**
 * Value of a line at the cursor's x — linearly interpolated between the two
 * bracketing points, and `null` when the cursor sits outside the series' own
 * x-range. Interpolating (rather than snapping to the nearest vertex) means the
 * distance we compare against is the distance to the drawn line; the range check
 * keeps a series that stops in June from being a hover target in November.
 */
function seriesYAt({ xs, ys }: LineSeries, x: number): number | null {
  let prevX = NaN;
  let prevY: number | null = null;
  for (let k = 0; k < xs.length; k++) {
    const y = ys[k];
    if (y == null) continue;
    const cx = xs[k];
    if (cx === x) return y;
    if (cx > x) {
      if (prevY == null) return null; // before the first drawn point
      const t = (x - prevX) / (cx - prevX);
      return prevY + t * (y - prevY);
    }
    prevX = cx;
    prevY = y;
  }
  return null; // after the last drawn point
}

/**
 * Track which line the pointer is nearest to (in data space — the value axes are
 * linear, so nearest-in-value is nearest-on-screen) and stash it on
 * `hoverIdxRef`; Chart.tsx's tooltip-formatter wrapper hands that to
 * `setHoveredSeries` the instant before the tip renders. On a change we re-show
 * the tip so the new emphasis lands the same frame (safe — the pointer no longer
 * snaps, so `x/y` matches the crosshair). The hit-test is coalesced to one run
 * per animation frame so a burst of mousemove events is cheap.
 */
function attachPointerTracker(
  inst: EC,
  linesRef: React.MutableRefObject<LineSeries[]>,
  hoverIdxRef: React.MutableRefObject<number>,
) {
  const zr = inst.getZr();
  let last = -2;
  let frame = 0;
  let pending: { offsetX: number; offsetY: number } | null = null;

  const commit = (next: number, ev?: { offsetX: number; offsetY: number }) => {
    hoverIdxRef.current = next;
    if (next === last) return;
    last = next;
    if (ev) inst.dispatchAction({ type: "showTip", x: ev.offsetX, y: ev.offsetY });
  };

  const handle = (ev: { offsetX: number; offsetY: number }) => {
    if (inst.isDisposed()) return;
    const lines = linesRef.current;
    if (lines.length < 2 || !inst.containPixel({ gridIndex: 0 }, [ev.offsetX, ev.offsetY])) {
      commit(-1);
      return;
    }
    const conv = inst.convertFromPixel({ gridIndex: 0 }, [ev.offsetX, ev.offsetY]) as
      | number[]
      | undefined;
    if (!conv) {
      commit(-1);
      return;
    }
    const [xData, yCursor] = conv;
    let best = -1;
    let bestDy = Infinity;
    for (const line of lines) {
      const y = seriesYAt(line, xData);
      if (y == null || Number.isNaN(y)) continue;
      const dy = Math.abs(y - yCursor);
      if (dy < bestDy) {
        bestDy = dy;
        best = line.i;
      }
    }
    commit(best, ev);
  };

  const onMove = (ev: { offsetX: number; offsetY: number }) => {
    pending = { offsetX: ev.offsetX, offsetY: ev.offsetY };
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (pending) handle(pending);
    });
  };
  zr.on("mousemove", onMove);
  zr.on("globalout", () => commit(-1));
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
  // this instance's hovered-line index — written by the pointer tracker, read
  // back into the module-level slot by the formatter wrapper below.
  const hoverIdxRef = useRef(-1);

  const merged = useMemo<EChartsOption>(() => {
    const base: EChartsOption = { ...BASE, ...option };
    const tip = (base as { tooltip?: { formatter?: unknown } }).tooltip;
    if (tip && typeof tip.formatter === "function") {
      const orig = tip.formatter as (...a: unknown[]) => unknown;
      (base as { tooltip?: unknown }).tooltip = {
        ...tip,
        // hand this instance's hovered index to options.ts right before its
        // formatter runs, so several mounted charts can't read each other's.
        formatter: (...a: unknown[]) => {
          setHoveredSeries(hoverIdxRef.current);
          return orig(...a);
        },
      };
    }
    return base;
  }, [option]);

  // line series for the pointer tracker; derived here, synced to the ref in an
  // effect so the zrender listener (attached once in onChartReady) sees fresh
  // data without a ref write during render.
  const lines = useMemo(() => deriveLines(merged), [merged]);
  const linesRef = useRef<LineSeries[]>(lines);
  useEffect(() => {
    linesRef.current = lines;
  }, [lines]);

  // echarts-for-react types the instance from its own bundled echarts; same
  // object at runtime, so bridge it here.
  const onChartReady = useCallback(
    (inst: unknown) => attachPointerTracker(inst as EC, linesRef, hoverIdxRef),
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
