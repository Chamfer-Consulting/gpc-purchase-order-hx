import { Alert, SimpleGrid, Stack, Text } from "@mantine/core";
import { Chart } from "@/charts/Chart";
import {
  barOption,
  horizontalBarOption,
  lineOption,
  stackedBarOption,
} from "@/charts/options";
import { AttentionList } from "./AttentionList";
import { DataGrid, type Column } from "./DataGrid";
import { KpiCard } from "./KpiCard";
import { ScopeBar } from "./ScopeBar";
import { SectionCard } from "./SectionCard";
import { formatCell } from "@/lib/format";
import type { ChartSpec, Kpi, PageResponse, TableSpec } from "@/api/schema";

function kpiValue(k: Kpi): string {
  return typeof k.value === "number" ? formatCell(k.value, k.format === "text" ? "text" : k.format) : String(k.value);
}

function chartOption(c: ChartSpec) {
  switch (c.kind) {
    case "bar":
      return barOption(c.x, c.series);
    case "stacked_bar":
      return stackedBarOption(c.x, c.series);
    case "hbar":
      return horizontalBarOption(
        c.x.map(String),
        (c.series[0]?.data ?? []).map((v) => v ?? 0),
        c.series[0]?.name,
      );
    case "area":
      return lineOption(c.x, c.series, { area: true });
    default:
      return lineOption(c.x, c.series);
  }
}

function tableColumns(t: TableSpec): Column<Record<string, unknown>>[] {
  return t.columns.map((c) => ({
    key: c.key,
    label: c.label,
    kind: c.kind,
    align: c.kind !== "text" && c.kind !== "date" ? "right" : "left",
    linkTo: c.key === "po_id" ? (v: unknown) => `/po/${v}` : undefined,
  }));
}

/** Renders a backend PageResponse: scope → attention → KPIs → charts → tables. */
export function PageRenderer({ data, showScope = true }: { data: PageResponse; showScope?: boolean }) {
  const tableEntries = Object.entries(data.tables);

  return (
    <Stack gap="lg">
      {showScope && (
        <ScopeBar
          count={data.scope.count}
          noun={data.scope.noun}
          start={data.scope.start ?? undefined}
          end={data.scope.end ?? undefined}
          extra={data.scope.note ?? undefined}
        />
      )}

      {data.attention.length > 0 && <AttentionList items={data.attention} />}

      {data.stub && (
        <Alert color="yellow" variant="light" title="Preview">
          Some numbers on this page come from a service that isn't fully wired yet.
        </Alert>
      )}

      {data.notes.map((n, i) => (
        <Text key={i} size="sm" c="dimmed">
          {n}
        </Text>
      ))}

      {data.kpis.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, md: Math.min(4, data.kpis.length) }}>
          {data.kpis.map((k, i) => (
            <KpiCard
              key={k.label}
              label={k.label}
              value={kpiValue(k)}
              delta={k.delta ?? null}
              deltaDirection={k.delta_direction ?? undefined}
              spark={k.spark ?? undefined}
              northStar={i === 0}
            />
          ))}
        </SimpleGrid>
      )}

      {data.charts.length > 0 && (
        <SimpleGrid cols={{ base: 1, lg: data.charts.length > 1 ? 2 : 1 }} spacing="lg">
          {data.charts.map((c) => (
            <SectionCard key={c.id} title={c.title || undefined}>
              <Chart option={chartOption(c)} empty={c.series.length === 0 || c.x.length === 0} />
            </SectionCard>
          ))}
        </SimpleGrid>
      )}

      {tableEntries.map(([key, t]) => (
        <SectionCard key={key} title={t.title || undefined}>
          <DataGrid rows={t.rows} columns={tableColumns(t)} exportName={t.export_name ?? key} />
        </SectionCard>
      ))}
    </Stack>
  );
}
