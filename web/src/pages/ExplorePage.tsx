import { useState } from "react";
import dayjs from "dayjs";
import {
  Alert,
  Divider,
  Group,
  Loader,
  MultiSelect,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useFilterOptions } from "@/api/filterOptions";
import {
  useCompare,
  usePivot,
  type ComparePeriods,
  type Dim,
  type Grain,
  type Measure,
} from "@/api/explore";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";

const DIMS: { value: Dim; label: string }[] = [
  { value: "customer", label: "Customer" },
  { value: "product", label: "Product" },
  { value: "size", label: "Size" },
];

const iso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : null);

export function ExplorePage() {
  const { data: opts } = useFilterOptions();
  const [measure, setMeasure] = useState<Measure>("revenue");
  const [grain, setGrain] = useState<Grain>("month");
  const [dims, setDims] = useState<Dim[]>(["customer"]);

  const pivot = usePivot({ measure, grain, dims });

  return (
    <Stack gap="md">
      <Title order={2}>Explore</Title>
      <Text size="sm" c="dimmed" maw={640}>
        Build any view: pick a measure, a time grain, and how to break it down. The full
        QuickBooks invoice history, for the current scope.
      </Text>

      <FilterBar
        customerOptions={opts?.customers ?? []}
        productOptions={opts?.products ?? []}
        sizeOptions={opts?.sizes ?? []}
        viewKind="explore"
      />

      <Paper withBorder radius="md" p="md">
        <Group gap="xl" wrap="wrap" align="flex-start">
          <Stack gap={4}>
            <Text size="xs" fw={600} c="dimmed">
              Measure
            </Text>
            <SegmentedControl
              size="xs"
              value={measure}
              onChange={(v) => setMeasure(v as Measure)}
              data={[
                { value: "revenue", label: "Revenue" },
                { value: "orders", label: "Orders" },
                { value: "quantity", label: "Quantity" },
              ]}
            />
          </Stack>
          <Stack gap={4}>
            <Text size="xs" fw={600} c="dimmed">
              Time grain
            </Text>
            <SegmentedControl
              size="xs"
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
          </Stack>
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
      </Paper>

      {pivot.error && (
        <Alert color="red" title="Couldn't load">
          {(pivot.error as Error).message}
        </Alert>
      )}
      {pivot.isLoading && <Loader />}
      {pivot.data && <PageRenderer data={pivot.data} />}

      <Divider my="sm" label="Compare two periods" labelPosition="left" />
      <ComparePanel />
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
    <Stack gap="sm">
      <Group gap="md" wrap="wrap">
        <DatePickerInput
          type="range"
          label="Period A"
          size="xs"
          w={230}
          value={a}
          onChange={setA}
          clearable
        />
        <DatePickerInput
          type="range"
          label="Period B"
          size="xs"
          w={230}
          value={b}
          onChange={setB}
          clearable
        />
      </Group>
      {!ranges && (
        <Text size="sm" c="dimmed">
          Pick a full start/end range for both periods.
        </Text>
      )}
      {cmp.error && (
        <Alert color="red" title="Couldn't load">
          {(cmp.error as Error).message}
        </Alert>
      )}
      {cmp.isLoading && <Loader />}
      {ranges && cmp.data && <PageRenderer data={cmp.data} />}
    </Stack>
  );
}
