/**
 * Option builders — the shapes the dashboard actually draws, so pages pass data,
 * not raw ECharts config. Each returns a plain option for <Chart>. The house
 * theme ("po-light"/"po-dark") supplies colour, gridlines, legend, axis style.
 *
 * The line/area builders lean "stock tracker": a gradient area fill, a snapping
 * cross-hair with value labels on both axes, and — for a single metric over time
 * — the line coloured green when it ends above where it started, red when below.
 */
import type { ChartBreakdown, NumFormat } from "@/api/schema";
import { fmtCurrency, fmtInt, fmtPercent } from "@/lib/format";
import { echarts, type EChartsOption } from "./echartsCore";
import type { Palette } from "./palette";

export interface Series {
  name: string;
  data: (number | null)[];
}

interface LineOpts {
  area?: boolean;
  /** active palette — enables green/red directional colouring for one series. */
  palette?: Palette;
  /** drives axis + tooltip number formatting. */
  fmt?: NumFormat;
  /** add a range slider under the plot (for long series). */
  zoom?: boolean;
  /** per-x constituent rows (top products / customers) shown in the tooltip. */
  breakdowns?: ChartBreakdown[] | null;
}

const compactUsd = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
  style: "currency",
  currency: "USD",
});
const compactNum = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** Short form for axis ticks: "$1.2M", "3.4k", "42%". */
export function axisFormatter(fmt: NumFormat = "int"): (v: number) => string {
  return (v) => {
    if (v == null || Number.isNaN(v)) return "";
    if (fmt === "currency" || fmt === "currency2") return compactUsd.format(v);
    if (fmt === "percent") return `${compactNum.format(v)}%`;
    return compactNum.format(v);
  };
}

/** Full form for tooltips + the cross-hair value label. */
export function valueFormatter(fmt: NumFormat = "int"): (v: number | string | null | undefined) => string {
  return (v) => {
    const n = Number(v);
    if (v == null || v === "" || Number.isNaN(n)) return "—";
    if (fmt === "currency") return fmtCurrency(n);
    if (fmt === "currency2") return fmtCurrency(n, true);
    if (fmt === "percent") return fmtPercent(n);
    return fmtInt(n);
  };
}

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
  if (!m) return hex;
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h, 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function areaGradient(hex: string) {
  return {
    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: hexToRgba(hex, 0.26) },
      { offset: 1, color: hexToRgba(hex, 0.01) },
    ]),
  };
}

/** first vs last non-null point — the "is this period up or down" test. */
function trendUp(data: (number | null)[]): boolean {
  const pts = data.filter((v): v is number => v != null && !Number.isNaN(v));
  return pts.length < 2 || pts[pts.length - 1] >= pts[0];
}

const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);

/** axis-trigger tooltip formatter that appends each breakdown's top rows
 *  (requested → shipped, or a single formatted value) behind the hovered x. */
function breakdownFormatter(fmt: NumFormat, breakdowns: ChartBreakdown[]) {
  const label = valueFormatter(fmt);
  type P = { axisValueLabel?: string; axisValue?: string | number; seriesName?: string; value?: unknown; marker?: unknown };
  return (raw: unknown) => {
    const arr = (Array.isArray(raw) ? raw : [raw]) as P[];
    const x = arr[0]?.axisValueLabel ?? arr[0]?.axisValue ?? "";
    const head = `<div style="font-weight:600;margin-bottom:2px">${esc(String(x))}</div>`;
    const series = arr
      .filter((p) => p.value != null)
      .map(
        (p) =>
          `${typeof p.marker === "string" ? p.marker : ""}${esc(p.seriesName ?? "")}: <b>${label(p.value as number)}</b>`,
      )
      .join("<br/>");
    const blocks = breakdowns
      .map((b) => {
        const pt = b.points.find((q) => String(q.x) === String(x));
        if (!pt || !pt.rows.length) return "";
        const rowFmt = valueFormatter(b.value_format ?? "currency");
        const rows = pt.rows
          .map((r) => {
            const right =
              r.requested != null && r.shipped != null
                ? `${label(r.requested)} &rarr; ${label(r.shipped)}`
                : rowFmt(r.value ?? 0);
            return (
              `<div style="display:flex;gap:14px;justify-content:space-between">` +
              `<span>${esc(r.name)}</span>` +
              `<span style="opacity:.7;white-space:nowrap">${right}</span>` +
              `</div>`
            );
          })
          .join("");
        return `<div style="margin-top:6px;font-weight:600;opacity:.65;font-size:11px">${esc(b.label)}</div>${rows}`;
      })
      .join("");
    return head + series + blocks;
  };
}

/** snapping cross-hair + formatted value labels; shared by the time-series builders. */
function crosshair(fmt: NumFormat, timeAxis = false) {
  const label = valueFormatter(fmt);
  return {
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "cross" as const, snap: true },
      confine: true,
      valueFormatter: (v: unknown) => label(v as number),
    },
    xAxis: {
      axisPointer: {
        show: true,
        // a raw timestamp on a time axis is unreadable — show a short date
        label: timeAxis ? { show: true, formatter: "{yyyy}-{MM}-{dd}" } : { show: true },
      },
    },
    yAxis: {
      axisPointer: {
        show: true,
        label: { show: true, formatter: (p: { value: unknown }) => label(p.value as number) },
      },
    },
  };
}

function zoomBits(enable: boolean) {
  if (!enable) return {};
  return {
    grid: { left: 8, right: 16, top: 40, bottom: 44, containLabel: true },
    dataZoom: [
      { type: "inside" as const },
      { type: "slider" as const, height: 16, bottom: 12, borderColor: "transparent" },
    ],
  };
}

/** Multi-series line over shared x categories (dates, months, ...). */
export function lineOption(x: (string | number)[], series: Series[], opts?: LineOpts): EChartsOption {
  const fmt = opts?.fmt ?? "int";
  const single = series.length === 1;
  const wantArea = opts?.area ?? single;
  const accent = single && opts?.palette ? (trendUp(series[0].data) ? opts.palette.status.good : opts.palette.status.critical) : undefined;
  const ch = crosshair(fmt);
  const tooltip = opts?.breakdowns?.length
    ? { ...ch.tooltip, formatter: breakdownFormatter(fmt, opts.breakdowns), confine: true }
    : ch.tooltip;
  return {
    ...ch,
    tooltip,
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "category", data: x, boundaryGap: false, ...ch.xAxis },
    // honest zero baseline — a revenue/count line zoomed to its own min..max
    // makes routine variation look like a cliff. (Price history keeps scale:true.)
    yAxis: { type: "value", axisLabel: { formatter: axisFormatter(fmt) }, ...ch.yAxis },
    ...zoomBits(!!opts?.zoom),
    series: series.map((s) => ({
      type: "line",
      name: s.name,
      data: s.data,
      // per-series, not chart-wide: a sparse series (a customer who only ordered
      // a few times against a long shared x-axis) has no adjacent non-null points
      // to draw a line between, so with symbols off it's invisible outright —
      // easy to read as "the chart is empty" once hover/legend-click blurs the
      // one dense series that WAS carrying the visible line.
      showSymbol: s.data.filter((v) => v != null).length <= 8,
      lineStyle: accent ? { color: accent } : undefined,
      itemStyle: accent ? { color: accent } : undefined,
      areaStyle: wantArea ? (accent ? areaGradient(accent) : { opacity: 0.08 }) : undefined,
    })),
  };
}

/** Multi-series line on a real time axis (irregular dates, e.g. price history). */
export function timeLineOption(
  series: { name: string; points: [string, number][] }[],
  opts?: { yName?: string; fmt?: NumFormat; palette?: Palette; markX?: string; markLabel?: string },
): EChartsOption {
  const fmt = opts?.fmt ?? "currency2";
  const single = series.length === 1;
  const accent =
    single && opts?.palette
      ? trendUp(series[0].points.map((p) => p[1]))
        ? opts.palette.status.good
        : opts.palette.status.critical
      : undefined;
  const ch = crosshair(fmt, true);
  const markLine = opts?.markX
    ? {
        silent: true,
        symbol: "none" as const,
        lineStyle: { type: "dashed" as const, opacity: 0.6 },
        label: {
          formatter: opts.markLabel ?? "",
          position: "insideEndTop" as const,
          textBorderWidth: 0,
          textShadowBlur: 0,
        },
        data: [{ xAxis: opts.markX }],
      }
    : undefined;

  return {
    ...ch,
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "time", ...ch.xAxis },
    // don't force a zero baseline — unit prices move in a narrow band. A y-axis
    // `name` defaults to sitting above the axis, right where the legend also
    // lives — put it vertically along the axis instead so the two can't collide.
    yAxis: {
      type: "value",
      scale: true,
      name: opts?.yName,
      nameLocation: "middle" as const,
      nameGap: 42,
      axisLabel: { formatter: axisFormatter(fmt) },
      ...ch.yAxis,
    },
    series: series.map((s, i) => ({
      type: "line",
      name: s.name,
      data: s.points,
      showSymbol: s.points.length <= 24,
      lineStyle: accent ? { color: accent } : undefined,
      itemStyle: accent ? { color: accent } : undefined,
      areaStyle: single ? (accent ? areaGradient(accent) : { opacity: 0.08 }) : undefined,
      markLine: i === 0 ? markLine : undefined,
    })),
  };
}

interface BarOpts {
  fmt?: NumFormat;
  breakdowns?: ChartBreakdown[] | null;
  /** colour each bar green/red by sign — for a month-over-month change series. */
  palette?: Palette;
  /** one extra tooltip line per x point (e.g. the absolute count behind a delta). */
  pointNotes?: (string | null)[] | null;
}

type TipParam = { axisValueLabel?: string; axisValue?: string | number; seriesName?: string; value?: unknown; marker?: unknown; dataIndex?: number };

/** shared axis-trigger tooltip for the bar builders. */
function barTooltip(
  fmt: NumFormat,
  breakdowns?: ChartBreakdown[] | null,
  signed = false,
  pointNotes?: (string | null)[] | null,
) {
  const label = valueFormatter(fmt);
  const show = (v: unknown) => {
    const s = label(v as number);
    return signed && Number(v) > 0 ? `+${s}` : s;
  };
  const base = { trigger: "axis" as const, axisPointer: { type: "shadow" as const }, confine: true };
  if (breakdowns?.length) return { ...base, formatter: breakdownFormatter(fmt, breakdowns) };
  if (pointNotes?.length) {
    return {
      ...base,
      formatter: (raw: unknown) => {
        const arr = (Array.isArray(raw) ? raw : [raw]) as TipParam[];
        const head = esc(String(arr[0]?.axisValueLabel ?? arr[0]?.axisValue ?? ""));
        const lines = arr
          .filter((p) => p.value != null)
          .map((p) => `${typeof p.marker === "string" ? p.marker : ""}${esc(p.seriesName ?? "")}: <b>${show(p.value)}</b>`);
        const note = pointNotes[arr[0]?.dataIndex ?? -1];
        return (
          `<div style="font-weight:600;margin-bottom:2px">${head}</div>` +
          lines.join("<br/>") +
          (note ? `<div style="margin-top:4px;opacity:.7">${esc(note)}</div>` : "")
        );
      },
    };
  }
  return { ...base, valueFormatter: (v: unknown) => show(v) };
}

/** Grouped or single vertical bars over x categories. A single series that dips
 *  below zero (a month-over-month change) gets per-bar green/red colouring. */
export function barOption(x: (string | number)[], series: Series[], opts?: BarOpts): EChartsOption {
  const fmt = opts?.fmt ?? "int";
  const diverging =
    !!opts?.palette && series.length === 1 && series[0].data.some((v) => v != null && v < 0);
  const up = opts?.palette?.status.good;
  const down = opts?.palette?.status.critical;
  return {
    tooltip: barTooltip(fmt, opts?.breakdowns, diverging, opts?.pointNotes),
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "category", data: x },
    yAxis: { type: "value", scale: diverging, axisLabel: { formatter: axisFormatter(fmt) } },
    series: series.map((s) => ({
      type: "bar",
      name: s.name,
      data:
        diverging
          ? s.data.map((v) => (v == null ? v : { value: v, itemStyle: { color: v >= 0 ? up : down } }))
          : s.data,
    })),
  };
}

/** Stacked vertical bars (e.g. product mix over months). */
export function stackedBarOption(x: (string | number)[], series: Series[], opts?: { fmt?: NumFormat }): EChartsOption {
  const label = valueFormatter(opts?.fmt ?? "int");
  return {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      confine: true,
      valueFormatter: (v: unknown) => label(v as number),
    },
    legend: {},
    xAxis: { type: "category", data: x },
    yAxis: { type: "value", axisLabel: { formatter: axisFormatter(opts?.fmt ?? "int") } },
    series: series.map((s) => ({ type: "bar", stack: "total", name: s.name, data: s.data })),
  };
}

/** Horizontal bars, sorted, for "top N by …". Value printed at each bar's end;
 *  long category names ellipsize (full name in the tooltip). */
export function horizontalBarOption(labels: string[], values: number[], name = "", opts?: BarOpts): EChartsOption {
  const fmt = opts?.fmt ?? "int";
  const label = valueFormatter(fmt);
  return {
    tooltip: barTooltip(fmt, opts?.breakdowns),
    legend: { show: false },
    grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", axisLabel: { formatter: axisFormatter(fmt) } },
    yAxis: {
      type: "category",
      data: labels,
      inverse: true,
      axisLabel: { width: 150, overflow: "truncate" },
    },
    series: [
      {
        type: "bar",
        name,
        data: values,
        label: {
          show: true,
          position: "right",
          formatter: (p: { value?: unknown }) => label(p.value as number),
          // style (colour / size / no halo) comes from the theme's `bar.label`
        },
      },
    ],
  };
}

/**
 * Bare sparkline for a KPI card — no axes, no grid. The last point is drawn as a
 * one-item overlay series so it reads as an emphasised endpoint without pulling in
 * the markPoint component.
 */
export function sparklineOption(values: number[], color: string): EChartsOption {
  const last = values.length - 1;
  const endpoint = values.map((v, i) => (i === last ? v : null));
  return {
    animation: false,
    grid: { left: 1, right: 1, top: 2, bottom: 2 },
    xAxis: { type: "category", show: false, boundaryGap: false, data: values.map((_, i) => i) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data: values,
        showSymbol: false,
        lineStyle: { width: 1.5, color },
        areaStyle: { opacity: 0.1, color },
      },
      {
        type: "line",
        data: endpoint,
        showSymbol: true,
        symbolSize: 5,
        itemStyle: { color },
        lineStyle: { opacity: 0 },
      },
    ],
  };
}
