/**
 * Option builders — the shapes the dashboard actually draws, so pages pass data,
 * not raw ECharts config. Each returns a plain option for <Chart>. The house
 * theme ("po-light"/"po-dark") supplies colour, gridlines, legend, axis style.
 */
import type { EChartsOption } from "./echartsCore";

export interface Series {
  name: string;
  data: (number | null)[];
}

/** Multi-series line over shared x categories (dates, months, ...). */
export function lineOption(x: (string | number)[], series: Series[], opts?: { area?: boolean }): EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "category", data: x, boundaryGap: false },
    yAxis: { type: "value" },
    series: series.map((s) => ({
      type: "line",
      name: s.name,
      data: s.data,
      areaStyle: opts?.area ? { opacity: 0.08 } : undefined,
      showSymbol: x.length <= 24,
    })),
  };
}

/** Grouped or single vertical bars over x categories. */
export function barOption(x: (string | number)[], series: Series[]): EChartsOption {
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: series.length > 1 ? {} : { show: false },
    xAxis: { type: "category", data: x },
    yAxis: { type: "value" },
    series: series.map((s) => ({ type: "bar", name: s.name, data: s.data })),
  };
}

/** Stacked vertical bars (e.g. product mix over months). */
export function stackedBarOption(x: (string | number)[], series: Series[]): EChartsOption {
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {},
    xAxis: { type: "category", data: x },
    yAxis: { type: "value" },
    series: series.map((s) => ({ type: "bar", stack: "total", name: s.name, data: s.data })),
  };
}

/** Horizontal bars, sorted, for "top N by …". */
export function horizontalBarOption(labels: string[], values: number[], name = ""): EChartsOption {
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { show: false },
    grid: { left: 8, right: 24, top: 12, bottom: 8, containLabel: true },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: labels, inverse: true },
    series: [{ type: "bar", name, data: values }],
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
