import ReactEChartsCore from "echarts-for-react/lib/core";
import { Group, Paper, Text } from "@mantine/core";
import { useComputedColorScheme } from "@mantine/core";
import { echarts } from "@/charts/echartsCore";
import { sparklineOption } from "@/charts/options";
import { paletteFor } from "@/charts/theme";

interface KpiCardProps {
  label: string;
  value: string;
  /** already-formatted delta string, e.g. "+12" / "−3.4%"; sign drives colour */
  delta?: string | null;
  deltaDirection?: "up" | "down" | "flat";
  spark?: number[];
}

export function KpiCard({ label, value, delta, deltaDirection, spark }: KpiCardProps) {
  const scheme = useComputedColorScheme("light");
  const p = paletteFor(scheme);

  const dir =
    deltaDirection ??
    (delta?.startsWith("+") ? "up" : delta?.startsWith("−") || delta?.startsWith("-") ? "down" : "flat");
  const deltaColor =
    dir === "up" ? p.status.good : dir === "down" ? p.status.critical : p.inkMuted;

  return (
    <Paper withBorder radius="md" p="md">
      <Text size="xs" c="dimmed" tt="uppercase" style={{ letterSpacing: "0.06em" }}>
        {label}
      </Text>
      <Group justify="space-between" align="flex-end" wrap="nowrap" mt={4}>
        <div>
          <Text fw={600} fz={26} lh={1.1} style={{ fontVariantNumeric: "tabular-nums" }}>
            {value}
          </Text>
          {delta != null && (
            <Text size="sm" mt={2} style={{ color: deltaColor, fontVariantNumeric: "tabular-nums" }}>
              {delta}
            </Text>
          )}
        </div>
        {spark && spark.length > 1 && (
          <ReactEChartsCore
            echarts={echarts}
            option={sparklineOption(spark, p.categorical[0])}
            style={{ width: 96, height: 40 }}
            opts={{ renderer: "canvas" }}
          />
        )}
      </Group>
    </Paper>
  );
}
