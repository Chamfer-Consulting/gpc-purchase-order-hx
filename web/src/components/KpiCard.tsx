import ReactEChartsCore from "echarts-for-react/lib/core";
import { Box, Group, Paper, Text, useComputedColorScheme } from "@mantine/core";
import { IconArrowDownRight, IconArrowRight, IconArrowUpRight } from "@tabler/icons-react";
import { echarts } from "@/charts/echartsCore";
import { sparklineOption } from "@/charts/options";
import { paletteFor } from "@/charts/theme";
import { NUMERIC_STYLE } from "@/theme/tokens";

interface KpiCardProps {
  label: string;
  value: string;
  /** already-formatted delta string, e.g. "+12" / "−3.4%"; sign drives colour */
  delta?: string | null;
  deltaDirection?: "up" | "down" | "flat";
  /** caption under the delta, e.g. "vs. prior 30 days" */
  deltaLabel?: string;
  spark?: number[];
  /** the page's primary metric — gets the harvest-gold accent underline */
  northStar?: boolean;
}

export function KpiCard({
  label,
  value,
  delta,
  deltaDirection,
  deltaLabel,
  spark,
  northStar = false,
}: KpiCardProps) {
  const scheme = useComputedColorScheme("light");
  const p = paletteFor(scheme);

  const dir =
    deltaDirection ??
    (delta?.startsWith("+") ? "up" : delta?.startsWith("−") || delta?.startsWith("-") ? "down" : "flat");
  const deltaColor =
    dir === "up" ? "var(--gp-status-good)" : dir === "down" ? "var(--gp-status-critical)" : "var(--mantine-color-dimmed)";
  const DeltaIcon = dir === "up" ? IconArrowUpRight : dir === "down" ? IconArrowDownRight : IconArrowRight;

  return (
    <Paper withBorder radius="md" p="md" bg="var(--gp-surface)" style={{ position: "relative", overflow: "hidden" }}>
      {northStar && (
        <Box
          style={{
            position: "absolute",
            insetInlineStart: 0,
            insetBlockEnd: 0,
            height: 3,
            width: "100%",
            background: "var(--gp-accent)",
          }}
        />
      )}
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: "0.06em" }}>
        {label}
      </Text>
      <Group justify="space-between" align="flex-end" wrap="nowrap" mt={6} gap="sm">
        <div style={{ minWidth: 0 }}>
          <Text fw={700} fz={26} lh={1.1} style={NUMERIC_STYLE}>
            {value}
          </Text>
          {delta != null && (
            <Group gap={4} mt={4} wrap="wrap">
              <DeltaIcon size={14} style={{ color: deltaColor, flex: "none" }} />
              <Text size="sm" style={{ color: deltaColor, ...NUMERIC_STYLE }}>
                {delta}
              </Text>
              {deltaLabel && (
                <Text size="xs" c="dimmed">
                  {deltaLabel}
                </Text>
              )}
            </Group>
          )}
        </div>
        {spark && spark.length > 1 && (
          <ReactEChartsCore
            echarts={echarts}
            option={sparklineOption(spark, p.categorical[0])}
            style={{ width: 96, height: 40, flex: "none" }}
            opts={{ renderer: "canvas" }}
          />
        )}
      </Group>
    </Paper>
  );
}
