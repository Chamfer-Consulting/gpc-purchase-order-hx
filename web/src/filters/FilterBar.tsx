import dayjs from "dayjs";
import { Group, MultiSelect, Switch } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useFilters } from "./useFilters";
import { SavedViewsControl } from "./SavedViewsControl";

interface FilterBarProps {
  customerOptions?: string[];
  productOptions?: string[];
  sizeOptions?: string[];
  showSamples?: boolean;
  /** when set, shows the saved-views control scoped to this page key */
  viewKind?: string;
}

// dayjs parses a bare ISO "YYYY-MM-DD" as LOCAL start-of-day (native `new Date`
// treats it as UTC), and formats in local time — so the picked day survives a
// URL round-trip in any timezone instead of shifting ±1.
const toDate = (s: string | null) => (s ? dayjs(s).toDate() : null);
const iso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : null);

/** The scope controls. State lives in the URL (useFilters) so views are shareable. */
export function FilterBar({
  customerOptions = [],
  productOptions = [],
  sizeOptions = [],
  showSamples = true,
  viewKind,
}: FilterBarProps) {
  const { filters, setFilters } = useFilters();

  return (
    <Group align="flex-end" gap="sm" wrap="wrap" mb="md">
      <DatePickerInput
        type="range"
        label="Date range"
        size="xs"
        w={230}
        value={[toDate(filters.start), toDate(filters.end)]}
        onChange={([s, e]) => setFilters({ start: iso(s), end: iso(e) })}
        clearable
      />
      <MultiSelect
        label="Customers"
        size="xs"
        w={220}
        data={customerOptions}
        value={filters.customers}
        onChange={(v) => setFilters({ customers: v })}
        searchable
        clearable
        nothingFoundMessage="No match"
      />
      <MultiSelect
        label="Products"
        size="xs"
        w={200}
        data={productOptions}
        value={filters.products}
        onChange={(v) => setFilters({ products: v })}
        searchable
        clearable
      />
      <MultiSelect
        label="Sizes"
        size="xs"
        w={140}
        data={sizeOptions}
        value={filters.sizes}
        onChange={(v) => setFilters({ sizes: v })}
        clearable
      />
      {showSamples && (
        <Switch
          label="Include samples"
          size="xs"
          mb={6}
          checked={filters.includeSamples}
          onChange={(e) => setFilters({ includeSamples: e.currentTarget.checked })}
        />
      )}
      {viewKind && <SavedViewsControl kind={viewKind} />}
    </Group>
  );
}
