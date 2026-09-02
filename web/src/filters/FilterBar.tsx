import dayjs from "dayjs";
import { Badge, Button, Divider, Drawer, Group, MultiSelect, Stack, Switch } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { DatePickerInput } from "@mantine/dates";
import { IconAdjustmentsHorizontal } from "@tabler/icons-react";
import { useFilters, type Filters } from "./useFilters";
import { RangePresets } from "./RangePresets";
import { SavedViewsControl } from "./SavedViewsControl";
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

/** The scope controls. State lives in the URL (useFilters) so views are shareable.
 *  Desktop: an inline wrapping row. Phone: quick-range chips + a "Filters" button
 *  that opens the full set in a bottom drawer. */
export function FilterBar(props: FilterBarProps) {
  const isMobile = useIsMobile();
  const { filters, setFilters } = useFilters();
  const [opened, { open, close }] = useDisclosure(false);

  const controls = <Controls {...props} full />;

  if (!isMobile) {
    return (
      <Group align="flex-end" gap="sm" wrap="wrap" mb="md">
        {controls}
      </Group>
    );
  }

  const n = activeCount(filters);
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

      <Drawer
        opened={opened}
        onClose={close}
        position="bottom"
        size="88%"
        title="Filters"
        padding="md"
      >
        <Stack gap="md">
          <Controls {...props} full stacked />
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

/** The individual filter inputs. `stacked` (drawer) makes each full-width; the
 *  desktop row keeps the fixed widths it was tuned with. */
function Controls({
  customerOptions = [],
  productOptions = [],
  sizeOptions = [],
  showSamples = true,
  hideCustomers = false,
  viewKind,
  stacked = false,
}: FilterBarProps & { full?: boolean; stacked?: boolean }) {
  const { filters, setFilters } = useFilters();
  const w = (fixed: number) => (stacked ? "100%" : fixed);

  return (
    <>
      <DatePickerInput
        type="range"
        label="Date range"
        size="xs"
        w={w(230)}
        value={[toDate(filters.start), toDate(filters.end)]}
        onChange={([s, e]) => setFilters({ start: iso(s), end: iso(e) })}
        clearable
      />
      {!stacked && (
        <div style={{ marginBottom: 6 }}>
          <RangePresets />
        </div>
      )}
      {!hideCustomers && (
        <MultiSelect
          label="Customers"
          size="xs"
          w={w(220)}
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
        w={w(200)}
        data={productOptions}
        value={filters.products}
        onChange={(v) => setFilters({ products: v })}
        searchable
        clearable
      />
      <MultiSelect
        label="Sizes"
        size="xs"
        w={w(140)}
        data={sizeOptions}
        value={filters.sizes}
        onChange={(v) => setFilters({ sizes: v })}
        clearable
      />
      {showSamples && (
        <Switch
          label="Include samples"
          size="xs"
          mb={stacked ? 0 : 6}
          checked={filters.includeSamples}
          onChange={(e) => setFilters({ includeSamples: e.currentTarget.checked })}
        />
      )}
      {viewKind && <SavedViewsControl kind={viewKind} />}
    </>
  );
}
