import { useId, useMemo, useState, type ReactNode } from "react";
import dayjs from "dayjs";
import { Badge, Group, MultiSelect, SegmentedControl, Stack, Tabs, Text } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useFilterOptions } from "@/api/filterOptions";
import type { TableSpec } from "@/api/schema";
import {
  useCompare,
  usePivot,
  type ComparePeriods,
  type Dim,
  type Grain,
  type Measure,
} from "@/api/explore";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer, tableColumns } from "@/components/PageRenderer";
import { DataGrid } from "@/components/DataGrid";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { FilterBar } from "@/filters/FilterBar";
import { pageMeta } from "@/nav";

const DIMS: { value: Dim; label: string }[] = [
  { value: "customer", label: "Customer" },
  { value: "product", label: "Product" },
  { value: "size", label: "Size" },
];

const iso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : null);

/** Label + control, associated for screen readers (SegmentedControl has no `label`). */
function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <Stack gap={4}>
      <Text id={id} size="xs" fw={600} c="dimmed">
        {label}
      </Text>
      {children(id)}
    </Stack>
  );
}

export function ExplorePage() {
  const { data: opts } = useFilterOptions();
  const meta = pageMeta("/explore")!;
  const [measure, setMeasure] = useState<Measure>("revenue");
  const [grain, setGrain] = useState<Grain>("month");
  const [dims, setDims] = useState<Dim[]>(["customer"]);

  const pivot = usePivot({ measure, grain, dims });

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      filterBar={
        <FilterBar
          customerOptions={opts?.customers ?? []}
          productOptions={opts?.products ?? []}
          sizeOptions={opts?.sizes ?? []}
          viewKind="explore"
        />
      }
    >
      <Stack gap="lg">
        <SectionCard title="Pivot" help="Pick a measure, a time grain, and how to break it down. Uses the full QuickBooks invoice history for the current scope.">
          <Group gap="xl" wrap="wrap" align="flex-start">
            <Field label="Measure">
              {(id) => (
                <SegmentedControl
                  size="xs"
                  aria-labelledby={id}
                  value={measure}
                  onChange={(v) => setMeasure(v as Measure)}
                  data={[
                    { value: "revenue", label: "Revenue" },
                    { value: "orders", label: "Orders" },
                    { value: "quantity", label: "Quantity" },
                  ]}
                />
              )}
            </Field>
            <Field label="Time grain">
              {(id) => (
                <SegmentedControl
                  size="xs"
                  aria-labelledby={id}
                  value={grain}
                  onChange={(v) => setGrain(v as Grain)}
                  data={[
                    { value: "day", label: "Day" },
                    { value: "week", label: "Week" },
                    { value: "month", label: "Month" },
                    { value: "quarter", label: "Quarter" },
                    { value: "year", label: "Year" },
                    { value: "all", label: "All time" },
                  ]}
                />
              )}
            </Field>
            <MultiSelect
              label="Break down by"
              size="xs"
              w={260}
              data={DIMS}
              value={dims}
              onChange={(v) => setDims(v as Dim[])}
              clearable
            />
          </Group>
        </SectionCard>

        <QueryBoundary loading={pivot.isLoading} error={pivot.error} onRetry={() => void pivot.refetch()}>
          {pivot.data && (
            <>
              <PageRenderer data={pivot.data} showScope={false} hideTables />
              {pivot.data.tables.pivot && (
                <SectionCard title={pivot.data.tables.pivot.title ?? "Pivot table"}>
                  <PivotTable table={pivot.data.tables.pivot} />
                </SectionCard>
              )}
            </>
          )}
        </QueryBoundary>

        <ComparePanel />
      </Stack>
    </PageLayout>
  );
}

function yearOf(period: unknown): number | null {
  const y = Number(String(period ?? "").slice(0, 4));
  return Number.isFinite(y) && y > 1900 ? y : null;
}

/** The pivot table, split into year tabs when it has a "period" column spanning
 *  more than one year — day/week/month grain × several years × a customer/product
 *  break-down otherwise reads as one undifferentiated wall of rows. Defaults to
 *  the most recent year rather than "All" (that's the whole point). */
function PivotTable({ table }: { table: TableSpec }) {
  const hasPeriod = table.columns.some((c) => c.key === "period");
  const columns = useMemo(() => tableColumns(table), [table]);
  const years = useMemo(() => {
    if (!hasPeriod) return [];
    const s = new Set<number>();
    for (const r of table.rows) {
      const y = yearOf(r.period);
      if (y != null) s.add(y);
    }
    return [...s].sort((a, b) => b - a);
  }, [table, hasPeriod]);

  const [pick, setPick] = useState<string | null>(null);
  const active = pick && (pick === "all" || years.includes(Number(pick)))
    ? pick
    : years.length > 1
      ? String(years[0])
      : "all";

  if (!hasPeriod || years.length <= 1) {
    return <DataGrid rows={table.rows} columns={columns} exportName={table.export_name ?? "pivot"} />;
  }

  const shown = active === "all" ? table.rows : table.rows.filter((r) => String(yearOf(r.period)) === active);

  return (
    <Stack gap="sm">
      <Tabs value={active} onChange={setPick}>
        <Tabs.List>
          {years.map((y) => (
            <Tabs.Tab
              key={y}
              value={String(y)}
              rightSection={
                <Badge size="xs" variant="light" color="gray">
                  {table.rows.filter((r) => yearOf(r.period) === y).length}
                </Badge>
              }
            >
              {y}
            </Tabs.Tab>
          ))}
          <Tabs.Tab
            value="all"
            rightSection={
              <Badge size="xs" variant="light" color="gray">
                {table.rows.length}
              </Badge>
            }
          >
            All years
          </Tabs.Tab>
        </Tabs.List>
      </Tabs>
      <DataGrid rows={shown} columns={columns} exportName={`${table.export_name ?? "pivot"}_${active}`} />
    </Stack>
  );
}

function ComparePanel() {
  const [a, setA] = useState<[Date | null, Date | null]>([null, null]);
  const [b, setB] = useState<[Date | null, Date | null]>([null, null]);

  const ranges: ComparePeriods | null =
    a[0] && a[1] && b[0] && b[1]
      ? { a_start: iso(a[0])!, a_end: iso(a[1])!, b_start: iso(b[0])!, b_end: iso(b[1])! }
      : null;

  const cmp = useCompare(ranges);

  return (
    <SectionCard title="Compare two periods">
      <Stack gap="sm">
        <Group gap="md" wrap="wrap">
          <DatePickerInput type="range" label="Period A" size="xs" w={230} value={a} onChange={setA} clearable />
          <DatePickerInput type="range" label="Period B" size="xs" w={230} value={b} onChange={setB} clearable />
        </Group>
        {!ranges ? (
          <Text size="sm" c="dimmed">
            Pick a full start/end range for both periods.
          </Text>
        ) : (
          <QueryBoundary loading={cmp.isLoading} error={cmp.error} onRetry={() => void cmp.refetch()}>
            {cmp.data && <PageRenderer data={cmp.data} showScope={false} />}
          </QueryBoundary>
        )}
      </Stack>
    </SectionCard>
  );
}
