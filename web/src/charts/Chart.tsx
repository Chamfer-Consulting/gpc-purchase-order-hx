import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useComputedColorScheme } from "@mantine/core";
import { echarts, type EChartsOption } from "./echartsCore";
import { chartHoverEvents } from "./options";
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

  // mouseover/mouseout/globalout keep the tooltip's hover-emphasis in sync;
  // any handler the caller passes for the same event still runs after.
  const events = useMemo<Record<string, (params: unknown) => void>>(() => {
    const out: Record<string, (params: unknown) => void> = { ...chartHoverEvents };
    for (const [name, fn] of Object.entries(onEvents ?? {})) {
      const base = out[name];
      out[name] = base
        ? (p: unknown) => {
            base(p);
            fn(p);
          }
        : fn;
    }
    return out;
  }, [onEvents]);

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
      style={{ height, width: "100%" }}
      className={className}
      onEvents={events}
    />
  );
}
