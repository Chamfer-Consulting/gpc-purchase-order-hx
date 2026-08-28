import { Group, MultiSelect, Switch } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useFilters } from "./useFilters";

interface FilterBarProps {
  customerOptions?: string[];
  productOptions?: string[];
  sizeOptions?: string[];
  showSamples?: boolean;
}

const toDate = (s: string | null) => (s ? new Date(s) : null);
const iso = (d: Date | null) => (d ? d.toISOString().slice(0, 10) : null);

/** The scope controls. State lives in the URL (useFilters) so views are shareable. */
export function FilterBar({
  customerOptions = [],
  productOptions = [],
  sizeOptions = [],
  showSamples = true,
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
    </Group>
  );
}
