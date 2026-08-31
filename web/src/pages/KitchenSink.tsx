import {
  Badge,
  Button,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { Chart } from "@/charts/Chart";
import { barOption, horizontalBarOption, lineOption, stackedBarOption } from "@/charts/options";
import { AttentionList } from "@/components/AttentionList";
import { DataGrid, type Column } from "@/components/DataGrid";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { KpiCard } from "@/components/KpiCard";
import { PageSkeleton } from "@/components/PageLayout";
import { ScopeBar } from "@/components/ScopeBar";
import { SectionCard } from "@/components/SectionCard";
import { fmtCurrency, fmtInt } from "@/lib/format";

const MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug"];
const PRODUCTS = ["Arugula", "Cilantro", "Rainbow Mix", "Genovese Basil", "Bulls Blood Beets"];

interface DemoRow extends Record<string, unknown> {
  customer: string;
  orders: number;
  revenue: number;
  fulfilment: number;
}
const ROWS: DemoRow[] = [
  { customer: "Get Fresh Produce", orders: 142, revenue: 88450, fulfilment: 98.2 },
  { customer: "Midwest Foods", orders: 96, revenue: 61200, fulfilment: 95.7 },
  { customer: "Testa Produce", orders: 54, revenue: 33900, fulfilment: 99.1 },
  { customer: "Anthony Marano", orders: 31, revenue: 12750, fulfilment: 91.4 },
];
const COLS: Column<DemoRow>[] = [
  { key: "customer", label: "Customer" },
  { key: "orders", label: "Orders", kind: "int" },
  { key: "revenue", label: "Revenue", kind: "currency" },
  { key: "fulfilment", label: "Fulfilment %", kind: "percent" },
];

const SWATCHES: [string, string][] = [
  ["Sprout green", "var(--mantine-color-gpGreen-6)"],
  ["Canopy", "var(--gp-canopy)"],
  ["Harvest gold", "var(--gp-accent)"],
  ["Good", "var(--gp-status-good)"],
  ["Warning", "var(--gp-status-warning)"],
  ["Serious", "var(--gp-status-serious)"],
  ["Critical", "var(--gp-status-critical)"],
  ["Page", "var(--gp-page)"],
  ["Surface", "var(--gp-surface)"],
  ["Border", "var(--gp-border)"],
];

export function KitchenSink() {
  return (
    <Stack gap="xl">
      <div>
        <Title order={1}>Style guide</Title>
        <Text size="sm" c="dimmed">
          The Garfield Produce design system — every shared component and state, in one place.
          Toggle the theme in the header to check light and dark.
        </Text>
      </div>

      <SectionCard title="Brand palette">
        <SimpleGrid cols={{ base: 2, sm: 3, md: 5 }}>
          {SWATCHES.map(([name, value]) => (
            <Stack key={name} gap={4}>
              <div
                style={{
                  height: 48,
                  borderRadius: "var(--mantine-radius-sm)",
                  background: value,
                  border: "1px solid var(--mantine-color-default-border)",
                }}
              />
              <Text size="xs">{name}</Text>
            </Stack>
          ))}
        </SimpleGrid>
      </SectionCard>

      <SectionCard title="Type scale">
        <Stack gap={4}>
          <Title order={1}>Heading 1 — Sora</Title>
          <Title order={2}>Heading 2 — Sora</Title>
          <Title order={3}>Heading 3 — Sora</Title>
          <Title order={4}>Heading 4 — Sora</Title>
          <Text>Body — Inter. The quick brown fox jumps over the lazy dog.</Text>
          <Text size="sm" c="dimmed">
            Small dimmed — supporting copy and captions.
          </Text>
          <Text style={{ fontVariantNumeric: "tabular-nums" }}>Tabular numerals 0123456789 · 1,234,567</Text>
        </Stack>
      </SectionCard>

      <SectionCard title="Buttons & controls">
        <Group>
          <Button>Primary</Button>
          <Button variant="light">Light</Button>
          <Button variant="default">Default</Button>
          <Button variant="subtle">Subtle</Button>
          <Button color="red" variant="light">
            Destructive
          </Button>
        </Group>
        <Group mt="md" align="flex-end">
          <TextInput label="Text input" placeholder="Type here" size="sm" />
          <SegmentedControl size="sm" data={["Revenue", "Orders", "Quantity"]} />
          <Switch label="Include samples" />
        </Group>
        <Group mt="md">
          <Badge color="gpGreen" variant="light">
            active
          </Badge>
          <Badge color="gpGold" variant="light">
            withdrawn
          </Badge>
          <Badge color="orange" variant="light">
            cancelled
          </Badge>
          <Badge color="red" variant="light">
            voided
          </Badge>
        </Group>
      </SectionCard>

      <ScopeBar count={323} noun="POs" start="2026-03-01" end="2026-08-31" />

      <SectionCard title="KPI cards (first = north-star)">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          <KpiCard
            label="Revenue"
            value={fmtCurrency(196300)}
            delta="+8.4%"
            deltaLabel="vs. prior 90d"
            spark={[120, 128, 119, 141, 150, 163]}
            northStar
          />
          <KpiCard label="Orders" value={fmtInt(323)} delta="+11" spark={[41, 44, 39, 52, 55, 48]} />
          <KpiCard label="Fulfilment" value="96.5%" delta="−0.7%" spark={[97, 98, 96, 95, 97, 96.5]} />
          <KpiCard label="Open POs" value={fmtInt(18)} delta="+3" deltaDirection="down" spark={[9, 11, 14, 12, 16, 18]} />
        </SimpleGrid>
      </SectionCard>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <SectionCard title="Revenue by month (line)">
          <Chart
            option={lineOption(MONTHS, [
              { name: "2026", data: [120, 128, 119, 141, 150, 163] },
              { name: "2025", data: [98, 104, 110, 121, 118, 130] },
            ])}
          />
        </SectionCard>
        <SectionCard title="Orders by customer (bar)">
          <Chart
            option={barOption(
              ROWS.map((r) => r.customer),
              [{ name: "Orders", data: ROWS.map((r) => r.orders) }],
            )}
          />
        </SectionCard>
        <SectionCard title="Product mix over time (stacked)">
          <Chart
            option={stackedBarOption(
              MONTHS,
              PRODUCTS.map((p, i) => ({
                name: p,
                data: MONTHS.map((_, m) => 20 + ((i * 7 + m * 3) % 30)),
              })),
            )}
          />
        </SectionCard>
        <SectionCard title="Top products by revenue (horizontal)">
          <Chart option={horizontalBarOption(PRODUCTS, [42000, 31500, 28800, 19400, 14100], "Revenue")} />
        </SectionCard>
      </SimpleGrid>

      <SectionCard title="Data grid">
        <DataGrid rows={ROWS} columns={COLS} exportName="demo" />
      </SectionCard>

      <SectionCard title="Needs attention">
        <AttentionList
          items={[
            { severity: "critical", title: "3 orders with a failed math check", count: 3, href: "/data-quality" },
            { severity: "serious", title: "5 unmatched invoices over $1k", count: 5, href: "/match" },
            { severity: "warning", title: "12 low-confidence extractions", count: 12, href: "/review" },
            { severity: "info", title: "QuickBooks sync ran 2h ago", count: 0, href: null },
          ]}
        />
      </SectionCard>

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="lg">
        <Paper withBorder radius="md" p="md">
          <Text size="sm" fw={600} mb="sm">
            Empty state
          </Text>
          <EmptyState title="No orders in range" description="Widen the date range or clear a filter." />
        </Paper>
        <Paper withBorder radius="md" p="md">
          <Text size="sm" fw={600} mb="sm">
            Error state
          </Text>
          <ErrorState error={new Error("Failed to fetch /api/overview")} onRetry={() => {}} compact />
        </Paper>
        <Paper withBorder radius="md" p="md">
          <Text size="sm" fw={600} mb="sm">
            Skeleton
          </Text>
          <PageSkeleton />
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}
