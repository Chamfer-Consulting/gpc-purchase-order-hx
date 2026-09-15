import { useMemo } from "react";
import {
  Group,
  MultiSelect,
  Select,
  SegmentedControl,
  SimpleGrid,
  Stack,
  TextInput,
  useComputedColorScheme,
} from "@mantine/core";
import type { ChartSpec, Kpi } from "@/api/schema";
import { useYieldMixes, useYieldProducts, useYieldTrends, type YieldGrain } from "@/api/yields";
import { barOption, lineOption } from "@/charts/options";
import { Chart } from "@/charts/Chart";
import { paletteFor } from "@/charts/theme";
import { ChartExportMenu } from "@/components/ChartExportMenu";
import { KpiCard } from "@/components/KpiCard";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { formatCell } from "@/lib/format";
import { pageMeta } from "@/nav";
import { useYieldFilters } from "./useYieldFilters";

function chartOption(c: ChartSpec, palette: ReturnType<typeof paletteFor>) {
  const opts = { palette, fmt: c.y_format };
  return c.kind === "bar" ? barOption(c.x, c.series, opts) : lineOption(c.x, c.series, opts);
}

function kpiValue(k: Kpi): string {
  return typeof k.value === "number" ? formatCell(k.value, k.format === "text" ? "text" : k.format) : String(k.value);
}

const GRAIN_OPTIONS = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

/** Office-facing weekly/monthly/quarterly/yearly rollups — harvest weight and
 *  tray harvested/discarded counts, mirroring how the PO side trends revenue.
 *  Own filter state (useYieldFilters) rather than the PO domain's useFilters:
 *  "product" here is a yield_product, a different universe from a sales SKU,
 *  and grain has no PO-side equivalent. */
export function YieldsTrendsPage() {
  const { filters, setFilters } = useYieldFilters();
  const products = useYieldProducts();
  const mixes = useYieldMixes();
  const meta = pageMeta("/yields");
  const palette = paletteFor(useComputedColorScheme("light"));

  const trends = useYieldTrends({
    date_from: filters.dateFrom ?? undefined,
    date_to: filters.dateTo ?? undefined,
    yield_product_id: filters.productIds.length ? filters.productIds : undefined,
    grain: filters.grain,
  });
  const data = trends.data;

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );

  const mixOptions = useMemo(
    () => (mixes.data ?? []).map((m) => ({ value: m.name, label: m.name })),
    [mixes.data],
  );
  // Controlled purely by comparison, not its own state — reflects "Rainbow
  // Mix" as selected only while the Products filter still exactly matches
  // that blend's full set, and clears itself the moment the admin tweaks
  // the individual selection away from it (add/remove a crop).
  const selectedMixName = useMemo(() => {
    const current = new Set(filters.productIds);
    const match = (mixes.data ?? []).find(
      (m) => m.yield_product_ids.length === current.size && m.yield_product_ids.every((id) => current.has(id)),
    );
    return match?.name ?? null;
  }, [mixes.data, filters.productIds]);

  const exportScope = [
    filters.dateFrom && filters.dateTo ? `${filters.dateFrom} – ${filters.dateTo}` : "All time",
    selectedMixName ??
      (filters.productIds.length
        ? `${filters.productIds.length} product${filters.productIds.length > 1 ? "s" : ""}`
        : null),
  ]
    .filter(Boolean)
    .join("  ·  ");

  return (
    <PageLayout
      title={meta?.title ?? "Product Yields"}
      description={meta?.description ?? "Harvest weight and tray trends over time."}
      breadcrumbs={meta?.breadcrumbs}
      filterBar={
        <Group gap="sm" wrap="wrap" align="flex-end">
          <TextInput
            type="date"
            label="From"
            size="xs"
            value={filters.dateFrom ?? ""}
            onChange={(e) => setFilters({ dateFrom: e.currentTarget.value || null })}
          />
          <TextInput
            type="date"
            label="To"
            size="xs"
            value={filters.dateTo ?? ""}
            onChange={(e) => setFilters({ dateTo: e.currentTarget.value || null })}
          />
          {mixOptions.length > 0 && (
            <Select
              label="Mix"
              placeholder="Pick a blend…"
              description="Sets Products below to that blend's crops"
              data={mixOptions}
              value={selectedMixName}
              onChange={(v) => {
                const mix = (mixes.data ?? []).find((m) => m.name === v);
                setFilters({ productIds: mix?.yield_product_ids ?? [] });
              }}
              clearable
              searchable
              size="xs"
              w={200}
            />
          )}
          <MultiSelect
            label="Products"
            placeholder="All products"
            data={productOptions}
            value={filters.productIds.map(String)}
            onChange={(v) => setFilters({ productIds: v.map(Number) })}
            searchable
            clearable
            size="xs"
            w={240}
          />
          <SegmentedControl
            value={filters.grain}
            onChange={(v) => setFilters({ grain: v as YieldGrain })}
            data={GRAIN_OPTIONS}
            size="xs"
          />
        </Group>
      }
      loading={trends.isLoading && !data}
      error={data ? undefined : trends.error}
      onRetry={() => void trends.refetch()}
    >
      {data && (
        <Stack gap="lg">
          {data.kpis.length > 0 && (
            <SimpleGrid cols={{ base: 1, sm: 2, md: Math.min(4, data.kpis.length) }}>
              {data.kpis.map((k) => (
                <KpiCard
                  key={k.label}
                  label={k.label}
                  value={kpiValue(k)}
                  delta={k.delta ?? null}
                  deltaDirection={k.delta_direction ?? undefined}
                  deltaLabel={k.delta_label ?? undefined}
                  help={k.help ?? undefined}
                  northStar={k.north_star}
                />
              ))}
            </SimpleGrid>
          )}

          {data.charts.map((c) => {
            const drawable = c.series.length > 0 && c.x.length > 0;
            const opt = chartOption(c, palette);
            return (
              <SectionCard
                key={c.id}
                title={c.title ?? undefined}
                actions={
                  drawable && c.title ? (
                    <ChartExportMenu option={opt} title={c.title} scope={exportScope} />
                  ) : undefined
                }
              >
                <Chart option={opt} empty={!drawable} height={320} />
              </SectionCard>
            );
          })}
        </Stack>
      )}
    </PageLayout>
  );
}
