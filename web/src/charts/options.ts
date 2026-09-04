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
  /** with `zoom`, the slider's initial window as [startPct, endPct] of the full
   *  series (e.g. [90, 100] to open already scrolled to the most recent ~10%) —
   *  the rest of the history is still there, one drag away. Default: fully zoomed
   *  out (0–100). */
  zoomWindow?: [number, number];
  /** per-x constituent rows (top products / customers) shown in the tooltip. */
  breakdowns?: ChartBreakdown[] | null;
  /** vertical reference lines (e.g. "show US holidays" toggle) — x must match a
   *  value in the chart's own `x` category array (an ISO date for a daily chart). */
  markX?: HolidayMark[];
}

export interface HolidayMark {
  x: string;
  name: string;
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

// --- hover emphasis -----------------------------------------------------------
// The axis tooltip lists every series at the hovered x; `_hoverSeries` is the
// line the cursor is nearest to. Chart.tsx writes it (via setHoveredSeries)
// immediately before each tooltip formatter runs, so with several charts mounted
// the slot always reflects the chart whose tip is rendering. The tooltip keeps
// that row lit and dims the rest; -1 = dim nothing.
let _hoverSeries = -1;

/** set by Chart.tsx's pointer tracker; -1 = nothing / outside the plot */
export function setHoveredSeries(i: number): void {
  _hoverSeries = i;
}

/** `active` is the row to keep lit (< 0 = keep every row lit). */
const emph = (active: number, si: number | undefined, row: string): string =>
  active < 0 || si === active ? row : `<span style="opacity:.4">${row}</span>`;

/** axis-trigger tooltip formatter: the hovered x, one row per series, then — if
 *  given — each breakdown's top rows (requested → shipped, or a single value). */
function axisTooltip(fmt: NumFormat, breakdowns: ChartBreakdown[] = []) {
  const label = valueFormatter(fmt);
  type P = {
    axisValueLabel?: string;
    axisValue?: string | number;
    seriesName?: string;
    seriesIndex?: number;
    value?: unknown;
    marker?: unknown;
  };
  // a category-axis point is a scalar; a time-axis point is the [x, y] pair
  const num = (v: unknown): number | null =>
    Array.isArray(v) ? (typeof v[1] === "number" ? v[1] : null) : typeof v === "number" ? v : null;
  return (raw: unknown) => {
    const arr = (Array.isArray(raw) ? raw : [raw]) as P[];
    const x = arr[0]?.axisValueLabel ?? arr[0]?.axisValue ?? "";
    const head = `<div style="font-weight:600;margin-bottom:2px">${esc(String(x))}</div>`;
    const rows = arr.filter((p) => num(p.value) != null);
    // only dim when the hovered line actually has a row here — if it has a gap
    // at this x, or the cursor is past its date range, light every row instead
    // of washing the whole tooltip out.
    const active = rows.some((p) => p.seriesIndex === _hoverSeries) ? _hoverSeries : -1;
    const series = rows
      .map((p) =>
        emph(
          active,
          p.seriesIndex,
          `${typeof p.marker === "string" ? p.marker : ""}${esc(p.seriesName ?? "")}: <b>${label(num(p.value) as number)}</b>`,
        ),
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

/** cross-hair + formatted value labels; shared by the time-series builders.
 *  No `snap` — a snapping pointer jumps point-to-point as the mouse moves, which
 *  reads as the whole tooltip stuttering. Let the cross-hair glide; the tooltip
 *  content still resolves to the nearest x. */
function crosshair(fmt: NumFormat, timeAxis = false) {
  const label = valueFormatter(fmt);
  return {
    // no `valueFormatter` — lineOption / timeLineOption always set their own
    // `formatter` (axisTooltip), which makes ECharts ignore valueFormatter.
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "cross" as const },
      confine: true,
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

function zoomBits(enable: boolean, window?: [number, number]) {
  if (!enable) return {};
  const [start, end] = window ?? [0, 100];
  return {
    grid: { left: 8, right: 16, top: 40, bottom: 44, containLabel: true },
    dataZoom: [
      { type: "inside" as const, start, end },
      { type: "slider" as const, start, end, height: 16, bottom: 12, borderColor: "transparent" },
    ],
  };
}

/** Vertical dashed reference lines for a "show US holidays" toggle — attach to
 *  one series only (index 0); ECharts draws a markLine chart-wide regardless of
 *  which series owns it. `x` values must match entries in the chart's own
 *  category axis data (an ISO date for a daily chart). */
function holidayMarkLine(marks?: HolidayMark[]) {
  if (!marks?.length) return undefined;
  return {
    silent: true,
    symbol: "none" as const,
    animation: false,
    lineStyle: { type: "dashed" as const, color: "var(--mantine-color-orange-5)", opacity: 0.55, width: 1 },
    label: {
      // "{b}" = the data point's own `name` (set below) — a template string
      // sidesteps ECharts' markLine label formatter-callback typing entirely.
      formatter: "{b}",
      position: "insideEndTop" as const,
      rotate: 90,
      fontSize: 10,
      color: "var(--mantine-color-orange-6)",
      textBorderWidth: 0,
      textShadowBlur: 0,
    },
    data: marks.map((m) => ({ xAxis: m.x, name: m.name })),
  };
}

/** Multi-series line over shared x categories (dates, months, ...). */
export function lineOption(x: (string | number)[], series: Series[], opts?: LineOpts): EChartsOption {
  const fmt = opts?.fmt ?? "int";
  const single = series.length === 1;
  const wantArea = opts?.area ?? single;
  const accent = single && opts?.palette ? (trendUp(series[0].data) ? opts.palette.status.good : opts.palette.status.critical) : undefined;
  const ch = crosshair(fmt);
  // Always a custom formatter (even with no breakdowns) so the row for the line
  // under the cursor is lit and the rest dimmed — matching the faded lines.
  const tooltip = {
    ...ch.tooltip,
    formatter: axisTooltip(fmt, opts?.breakdowns ?? []),
    confine: true,
  };
  // Point markers are a chart-wide decision, not per-series: mixing dotted and
  // dotless lines on one plot reads as a rendering bug. Show them on every line
  // when ANY series is sparse enough that its line would otherwise be near-
  // invisible (isolated non-null points with nothing adjacent to connect);
  // otherwise every dense line stays clean.
  const showDots = series.some((s) => s.data.filter((v) => v != null).length <= 8);
  return {
    ...ch,
    tooltip,
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "category", data: x, boundaryGap: false, ...ch.xAxis },
    // honest zero baseline — a revenue/count line zoomed to its own min..max
    // makes routine variation look like a cliff. (Price history keeps scale:true.)
    yAxis: { type: "value", axisLabel: { formatter: axisFormatter(fmt) }, ...ch.yAxis },
    ...zoomBits(!!opts?.zoom, opts?.zoomWindow),
    series: series.map((s, i) => ({
      type: "line",
      name: s.name,
      data: s.data,
      showSymbol: showDots,
      lineStyle: accent ? { color: accent } : undefined,
      itemStyle: accent ? { color: accent } : undefined,
      areaStyle: wantArea ? (accent ? areaGradient(accent) : { opacity: 0.08 }) : undefined,
      markLine: i === 0 ? holidayMarkLine(opts?.markX) : undefined,
    })),
  };
}

/** How a time series is drawn:
 *  solid (default) · ghost (faded/dashed context, e.g. a pre-standardization era)
 *  · trend (thick overlay) · reference (thin flat guide line). */
export type TimeSeriesVariant = "solid" | "ghost" | "trend" | "reference";

export interface TimeSeries {
  name: string;
  points: [string, number][];
  variant?: TimeSeriesVariant;
}

/** Multi-series line on a real time axis (irregular dates, e.g. price history). */
export function timeLineOption(
  series: TimeSeries[],
  opts?: {
    yName?: string;
    fmt?: NumFormat;
    palette?: Palette;
    markX?: string;
    markLabel?: string;
    /** shaded x-range (e.g. a transition period), drawn behind every series */
    bandX?: [string, string];
    bandLabel?: string;
  },
): EChartsOption {
  const fmt = opts?.fmt ?? "currency2";
  const drawn = series.filter((s) => (s.points?.length ?? 0) > 0);
  const solids = drawn.filter((s) => !s.variant || s.variant === "solid");
  const single = drawn.length === 1 && solids.length === 1;
  const accent =
    single && opts?.palette
      ? trendUp(drawn[0].points.map((p) => p[1]))
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
  const markArea = opts?.bandX
    ? {
        silent: true,
        itemStyle: { color: "var(--mantine-color-default-border)", opacity: 0.35 },
        label: {
          show: !!opts.bandLabel,
          formatter: opts.bandLabel ?? "",
          position: "insideTop" as const,
          color: "var(--mantine-color-dimmed)",
          fontSize: 11,
          textBorderWidth: 0,
          textShadowBlur: 0,
        },
        data: [[{ xAxis: opts.bandX[0] }, { xAxis: opts.bandX[1] }]] as [
          [{ xAxis: string }, { xAxis: string }],
        ],
      }
    : undefined;

  // Point markers: chart-wide, so solid lines don't disagree with each other.
  // On when any solid series is sparse enough to otherwise render near-invisible.
  const showDots = solids.some((s) => s.points.length <= 24);

  // legend: only the solid/trend series carry a distinct entry — a ghost shares
  // its solid partner's name, so ECharts folds the two onto one toggle.
  const legendNames = Array.from(
    new Set(drawn.filter((s) => s.variant !== "reference").map((s) => s.name)),
  );

  return {
    ...ch,
    tooltip: { ...ch.tooltip, formatter: axisTooltip(fmt), confine: true },
    legend: legendNames.length > 1 ? { data: legendNames } : { show: false },
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
    // one uniform object shape per series (some fields undefined) so the array
    // stays homogeneous for ECharts' SeriesOption typing
    series: drawn.map((s, i) => {
      const v = s.variant ?? "solid";
      const solid = v === "solid";
      const dashed =
        v === "ghost"
          ? { type: "dashed" as const, opacity: 0.3, width: 1 }
          : v === "reference"
            ? { type: "dashed" as const, width: 1, opacity: 0.5 }
            : v === "trend"
              ? { width: 3 }
              : accent
                ? { color: accent }
                : undefined;
      return {
        type: "line" as const,
        name: s.name,
        data: s.points,
        // only the plain data lines are hover-emphasis targets — the ghost /
        // flat reference / smoothed trend overlays are read by Chart.tsx's
        // pointer tracker otherwise and would steal emphasis from the real row.
        __track: v === "solid",
        markLine: i === 0 ? markLine : undefined,
        markArea: i === 0 ? markArea : undefined,
        smooth: v === "trend",
        silent: v === "reference",
        z: v === "ghost" ? 1 : v === "reference" ? 2 : v === "trend" ? 6 : undefined,
        emphasis: v === "trend" ? { disabled: true } : undefined,
        showSymbol: solid ? showDots : false,
        lineStyle: dashed,
        itemStyle: v === "ghost" ? { opacity: 0.3 } : accent && solid ? { color: accent } : undefined,
        areaStyle:
          single && solid ? (accent ? areaGradient(accent) : { opacity: 0.08 }) : undefined,
      };
    }),
  };
}

interface BarOpts {
  fmt?: NumFormat;
  breakdowns?: ChartBreakdown[] | null;
  /** colour each bar green/red by sign — for a month-over-month change series. */
  palette?: Palette;
  /** one extra tooltip line per x point (e.g. the absolute count behind a delta). */
  pointNotes?: (string | null)[] | null;
  /** add a range slider under the plot (for long series — e.g. a daily chart). */
  zoom?: boolean;
  /** with `zoom`, the slider's initial window as [startPct, endPct]. Default:
   *  fully zoomed out (0–100). */
  zoomWindow?: [number, number];
  /** vertical reference lines (e.g. "show US holidays" toggle). */
  markX?: HolidayMark[];
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
  if (breakdowns?.length) return { ...base, formatter: axisTooltip(fmt, breakdowns) };
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
    ...zoomBits(!!opts?.zoom, opts?.zoomWindow),
    series: series.map((s, i) => ({
      type: "bar",
      name: s.name,
      data:
        diverging
          ? s.data.map((v) => (v == null ? v : { value: v, itemStyle: { color: v >= 0 ? up : down } }))
          : s.data,
      markLine: i === 0 ? holidayMarkLine(opts?.markX) : undefined,
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
