import { useMemo, useState } from "react";
import dayjs from "dayjs";
import {
  Badge,
  Button,
  Checkbox,
  Divider,
  Drawer,
  Group,
  MultiSelect,
  ScrollArea,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { DatePicker, DatePickerInput } from "@mantine/dates";
import { IconAdjustmentsHorizontal, IconCheck, IconSearch } from "@tabler/icons-react";
import { useFilters, type Filters } from "./useFilters";
import { PRESETS, RangePresets, activePreset, rangeFor } from "./RangePresets";
import { SavedViewsControl } from "./SavedViewsControl";
import { FilterPill } from "./FilterPill";
import { useIsMobile } from "@/hooks/useIsMobile";

interface FilterBarProps {
  customerOptions?: string[];
  productOptions?: string[];
  sizeOptions?: string[];
  showSamples?: boolean;
  /** hide the customer selector — the customer detail page fixes it via the route */
  hideCustomers?: boolean;
  /** when set, shows the saved-views control scoped to this page key */
  viewKind?: string;
}

// dayjs parses a bare ISO "YYYY-MM-DD" as LOCAL start-of-day (native `new Date`
// treats it as UTC), and formats in local time — so the picked day survives a
// URL round-trip in any timezone instead of shifting ±1.
const toDate = (s: string | null) => (s ? dayjs(s).toDate() : null);
const iso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : null);

const EMPTY: Partial<Filters> = {
  start: null,
  end: null,
  customers: [],
  products: [],
  sizes: [],
  includeSamples: false,
};

function activeCount(f: Filters): number {
  return (
    f.customers.length +
    f.products.length +
    f.sizes.length +
    (f.start || f.end ? 1 : 0) +
    (f.includeSamples ? 1 : 0)
  );
}

/**
 * The dashboard scope. State lives in the URL (useFilters) so views are
 * shareable. Desktop: a row of same-shape filter "pills" that each open a
 * popover — the row stays aligned and one line tall however many values are
 * picked. Phone: quick-range chips + a "Filters" button opening a bottom drawer.
 */
export function FilterBar(props: FilterBarProps) {
  const isMobile = useIsMobile();
  const { filters, setFilters } = useFilters();
  const [opened, { open, close }] = useDisclosure(false);
  const n = activeCount(filters);

  if (!isMobile) {
    return (
      <Group align="center" gap="xs" wrap="wrap">
        <DatePill />

        {!props.hideCustomers && (
          <FilterPill label="Customers" count={filters.customers.length}>
            <MultiCheck
              data={props.customerOptions ?? []}
              value={filters.customers}
              onChange={(v) => setFilters({ customers: v })}
            />
          </FilterPill>
        )}
        <FilterPill label="Products" count={filters.products.length}>
          <MultiCheck
            data={props.productOptions ?? []}
            value={filters.products}
            onChange={(v) => setFilters({ products: v })}
          />
        </FilterPill>
        <FilterPill label="Sizes" count={filters.sizes.length} width={200}>
          <MultiCheck
            data={props.sizeOptions ?? []}
            value={filters.sizes}
            onChange={(v) => setFilters({ sizes: v })}
            searchable={false}
          />
        </FilterPill>

        {(props.showSamples ?? true) && (
          <Button
            size="xs"
            variant={filters.includeSamples ? "light" : "default"}
            color={filters.includeSamples ? "gpGreen" : "gray"}
            leftSection={
              <IconCheck
                size={13}
                style={{ opacity: filters.includeSamples ? 1 : 0.25 }}
              />
            }
            styles={{ label: { fontWeight: 500 } }}
            onClick={() => setFilters({ includeSamples: !filters.includeSamples })}
          >
            Samples
          </Button>
        )}

        {n > 0 && (
          <Button size="xs" variant="subtle" color="red" onClick={() => setFilters(EMPTY)}>
            Clear
          </Button>
        )}

        {props.viewKind && (
          <Group ml="auto" gap={4} align="center">
            <SavedViewsControl kind={props.viewKind} />
          </Group>
        )}
      </Group>
    );
  }

  return (
    <Group gap="xs" wrap="nowrap" style={{ overflowX: "auto" }}>
      <RangePresets />
      <Button
        size="xs"
        variant="default"
        leftSection={<IconAdjustmentsHorizontal size={14} />}
        onClick={open}
        style={{ flex: "none" }}
      >
        Filters
        {n > 0 && (
          <Badge size="xs" ml={6} variant="filled" color="gpGreen">
            {n}
          </Badge>
        )}
      </Button>

      <Drawer opened={opened} onClose={close} position="bottom" size="88%" title="Filters" padding="md">
        <Stack gap="md">
          <StackedControls {...props} />
          <Divider />
          <Group justify="space-between">
            <Button
              size="xs"
              variant="subtle"
              color="red"
              disabled={n === 0}
              onClick={() => setFilters(EMPTY)}
            >
              Clear all
            </Button>
            <Button size="xs" onClick={close}>
              Done
            </Button>
          </Group>
        </Stack>
      </Drawer>
    </Group>
  );
}

/* -------------------------------------------------------------------------- */

/** Desktop date pill — presets + an inline range calendar. The button shows the
 *  resolved window ("Past month", "Sep 1 – Sep 30") so the current scope reads at
 *  a glance without opening it. */
function DatePill() {
  const { filters, setFilters } = useFilters();
  const preset = activePreset(filters);

  let label: string | undefined;
  if (preset) {
    label = PRESETS.find((p) => p.id === preset)?.long;
  } else if (filters.start || filters.end) {
    const f = (s: string | null) => (s ? dayjs(s).format("MMM D, YYYY") : "…");
    label = `${f(filters.start)} – ${f(filters.end)}`;
  }

  return (
    <FilterPill label="Any date" value={label} width={290}>
      <Stack gap={8}>
        <Group gap={4}>
          {PRESETS.map(({ id, label: short }) => {
            const r = rangeFor(id);
            const active = filters.start === r.start && filters.end === r.end;
            return (
              <Button
                key={id}
                size="compact-xs"
                variant={active ? "filled" : "default"}
                onClick={() => setFilters({ start: r.start, end: r.end })}
              >
                {short}
              </Button>
            );
          })}
        </Group>
        <DatePicker
          type="range"
          size="xs"
          allowSingleDateInRange
          value={[toDate(filters.start), toDate(filters.end)]}
          onChange={([s, e]) => setFilters({ start: iso(s), end: iso(e) })}
        />
      </Stack>
    </FilterPill>
  );
}

/** Searchable checkbox list for the desktop Customers / Products / Sizes pills —
 *  self-contained (no nested dropdown) so it always aligns inside the popover. */
function MultiCheck({
  data,
  value,
  onChange,
  searchable = true,
}: {
  data: string[];
  value: string[];
  onChange: (v: string[]) => void;
  searchable?: boolean;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? data.filter((d) => d.toLowerCase().includes(needle)) : data;
  }, [data, q]);

  return (
    <Stack gap={6}>
      {searchable && (
        <TextInput
          size="xs"
          placeholder="Search…"
          data-autofocus
          leftSection={<IconSearch size={13} />}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
        />
      )}
      <ScrollArea.Autosize mah={240} type="auto">
        {shown.length === 0 ? (
          <Text size="xs" c="dimmed" ta="center" py="xs">
            No match
          </Text>
        ) : (
          <Checkbox.Group value={value} onChange={onChange}>
            <Stack gap={4} pr={4}>
              {shown.map((o) => (
                <Checkbox key={o} value={o} label={o} size="xs" />
              ))}
            </Stack>
          </Checkbox.Group>
        )}
      </ScrollArea.Autosize>
      {value.length > 0 && (
        <Button size="compact-xs" variant="subtle" color="red" onClick={() => onChange([])}>
          Clear {value.length}
        </Button>
      )}
    </Stack>
  );
}

/** The mobile drawer body — full-width, labelled inputs stacked vertically. */
function StackedControls({
  customerOptions = [],
  productOptions = [],
  sizeOptions = [],
  showSamples = true,
  hideCustomers = false,
  viewKind,
}: FilterBarProps) {
  const { filters, setFilters } = useFilters();

  return (
    <>
      <DatePickerInput
        type="range"
        label="Date range"
        size="xs"
        w="100%"
        value={[toDate(filters.start), toDate(filters.end)]}
        onChange={([s, e]) => setFilters({ start: iso(s), end: iso(e) })}
        clearable
      />
      <RangePresets />
      {!hideCustomers && (
        <MultiSelect
          label="Customers"
          size="xs"
          w="100%"
          data={customerOptions}
          value={filters.customers}
          onChange={(v) => setFilters({ customers: v })}
          searchable
          clearable
          nothingFoundMessage="No match"
        />
      )}
      <MultiSelect
        label="Products"
        size="xs"
        w="100%"
        data={productOptions}
        value={filters.products}
        onChange={(v) => setFilters({ products: v })}
        searchable
        clearable
      />
      <MultiSelect
        label="Sizes"
        size="xs"
        w="100%"
        data={sizeOptions}
        value={filters.sizes}
        onChange={(v) => setFilters({ sizes: v })}
        clearable
      />
      {showSamples && (
        <Switch
          label="Include samples"
          size="xs"
          checked={filters.includeSamples}
          onChange={(e) => setFilters({ includeSamples: e.currentTarget.checked })}
        />
      )}
      {viewKind && <SavedViewsControl kind={viewKind} stacked />}
    </>
  );
}
