/**
 * The single house chart style, ported from dashboard/data.py:style():
 * borderless surface, one hairline horizontal gridline set, no tick marks or axis
 * spines, legend as a top strip, dashed cursor spike, unified hover, brand
 * colourway, tabular numerals. Registered as two ECharts themes ("po-light" /
 * "po-dark"); <Chart> picks one from the active Mantine colour scheme.
 */
import { DARK, FONT_FAMILY, LIGHT, type Palette } from "./palette";
import { echarts } from "./echartsCore";

export type Scheme = "light" | "dark";

function themeObject(p: Palette): Record<string, unknown> {
  const label = { color: p.inkMuted, fontSize: 11, fontFamily: FONT_FAMILY };
  const cleanAxis = {
    axisLine: { show: false },
    axisTick: { show: false, length: 0 },
    axisLabel: label,
    splitLine: { show: false },
    nameTextStyle: { color: p.inkMuted, fontSize: 11 },
  };
  const valueAxis = {
    ...cleanAxis,
    splitLine: { show: true, lineStyle: { color: p.grid, width: 1 } },
  };

  return {
    color: p.categorical,
    backgroundColor: "transparent",
    textStyle: { fontFamily: FONT_FAMILY, color: p.inkPrimary, fontSize: 12 },

    title: {
      left: 0,
      textStyle: { color: p.inkMuted, fontWeight: 600, fontSize: 13, fontFamily: FONT_FAMILY },
    },

    legend: {
      type: "scroll",
      top: 0,
      left: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: p.inkMuted, fontSize: 11, fontFamily: FONT_FAMILY },
      pageIconColor: p.inkMuted,
      pageTextStyle: { color: p.inkMuted },
    },

    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },

    categoryAxis: cleanAxis,
    valueAxis,
    logAxis: valueAxis,
    timeAxis: cleanAxis,

    tooltip: {
      trigger: "axis",
      backgroundColor: p.surface,
      borderColor: p.grid,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: p.inkPrimary, fontFamily: FONT_FAMILY, fontSize: 12 },
      axisPointer: {
        type: "line",
        lineStyle: { color: p.inkMuted, width: 1, type: "dashed" },
        crossStyle: { color: p.inkMuted },
        label: { backgroundColor: p.inkMuted },
      },
    },

    // data labels drawn on/near a series: plain ink text, NO white halo
    // (ECharts' default text-border makes small numbers muddy and hard to read).
    line: {
      symbol: "circle",
      symbolSize: 6,
      smooth: false,
      lineStyle: { width: 2 },
      label: { color: p.inkPrimary, fontSize: 11, textBorderWidth: 0, textShadowBlur: 0 },
      emphasis: { focus: "series" },
      // hovering one legend entry (or one line) fades the rest — ECharts' default
      // blur opacity (~0.1) reads as "the other series vanished"; keep them faintly
      // present as context instead of near-invisible.
      blur: { lineStyle: { opacity: 0.28 }, itemStyle: { opacity: 0.28 }, areaStyle: { opacity: 0.05 } },
    },
    bar: {
      barMaxWidth: 42,
      itemStyle: { borderWidth: 0, borderRadius: [2, 2, 0, 0] },
      label: { color: p.inkPrimary, fontSize: 11, textBorderWidth: 0, textShadowBlur: 0 },
      emphasis: { focus: "series" },
      blur: { itemStyle: { opacity: 0.28 } },
    },
    pie: {
      itemStyle: { borderColor: p.surface, borderWidth: 1 },
      label: { color: p.inkMuted, fontSize: 11 },
    },
  };
}

let registered = false;
export function registerChartThemes(): void {
  if (registered) return;
  echarts.registerTheme("po-light", themeObject(LIGHT));
  echarts.registerTheme("po-dark", themeObject(DARK));
  registered = true;
}

export const paletteFor = (scheme: Scheme): Palette => (scheme === "dark" ? DARK : LIGHT);
export const themeNameFor = (scheme: Scheme): string => (scheme === "dark" ? "po-dark" : "po-light");
