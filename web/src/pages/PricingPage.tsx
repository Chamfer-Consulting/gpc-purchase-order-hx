import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { Chart } from "@/charts/Chart";
import { timeLineOption, type TimeSeries } from "@/charts/options";
import { fmtCurrency } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/notify";
import { useMe } from "@/api/me";
import {
  useReferencePrices,
  usePriceHistory,
  useSavePrices,
  type PriceHistory,
  type PricePoint,
  type ReferencePrice,
  type RefPriceRow,
} from "@/api/pricing";
import { PageLayout } from "@/components/PageLayout";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { pageMeta } from "@/nav";

interface EditRow {
  _rk: number;
  id: number | null;
  customer_name: string;
  product_name: string;
  container_size: string;
  price: number | "";
  source: string;
}

let RK = 1;

// key parts are joined on U+241F (never present in a name) so a name's own
// spaces / slashes don't corrupt the round-trip through the deleted-keys set.
const SEP = "␟";
const keyOf = (r: { customer_name: string; product_name: string; container_size: string }) =>
  [r.customer_name, r.product_name, r.container_size].join(SEP);

function seedRows(refs: ReferencePrice[]): EditRow[] {
  return refs.map((r) => ({
    _rk: RK++,
    id: r.id,
    customer_name: r.customer_name,
    product_name: r.product_name,
    container_size: r.container_size,
    price: r.price,
    source: r.source,
  }));
}

export function PricingPage() {
  const { data, isLoading, error, refetch } = useReferencePrices();
  const save = useSavePrices();
  const meta = pageMeta("/pricing")!;
  const { canAdmin, roleKnown } = useMe();

  const [rows, setRows] = useState<EditRow[]>([]);
  const [seed, setSeed] = useState<Map<string, number>>(new Map());

  useEffect(() => {
    if (!data) return;
    setRows(seedRows(data.reference_prices));
    setSeed(new Map(data.reference_prices.map((r) => [keyOf(r), r.price] as const)));
  }, [data]);

  const products = useMemo(
    () => Array.from(new Set(data?.options.map((o) => o.product_name) ?? [])).sort(),
    [data],
  );
  const [product, setProduct] = useState<string | null>(null);
  const sizes = useMemo(
    () =>
      Array.from(
        new Set(
          (data?.options ?? [])
            .filter((o) => o.product_name === product)
            .map((o) => o.container_size),
        ),
      ).sort(),
    [data, product],
  );
  const [size, setSize] = useState<string | null>(null);
  useEffect(() => {
    if (product && sizes.length && !sizes.includes(size ?? "")) setSize(sizes[0]);
  }, [product, sizes, size]);

  function patch(rk: number, p: Partial<EditRow>) {
    setRows((rs) => rs.map((r) => (r._rk === rk ? { ...r, ...p } : r)));
  }
  function addRow() {
    setRows((rs) => [
      ...rs,
      {
        _rk: RK++,
        id: null,
        customer_name: "",
        product_name: product ?? "",
        container_size: size ?? "",
        price: "",
        source: "manual",
      },
    ]);
  }
  function removeRow(rk: number) {
    setRows((rs) => rs.filter((r) => r._rk !== rk));
  }

  function onSave() {
    if (!canAdmin) return;
    const present = new Set<string>();
    const changed: RefPriceRow[] = [];
    for (const r of rows) {
      const cust = r.customer_name.trim();
      const prod = r.product_name.trim();
      const sz = r.container_size.trim();
      if (!cust || !prod || !sz || r.price === "" || Number.isNaN(Number(r.price))) continue;
      const k = keyOf({ customer_name: cust, product_name: prod, container_size: sz });
      present.add(k);
      const prev = seed.get(k);
      if (prev === undefined || Number(prev) !== Number(r.price)) {
        changed.push({ customer_name: cust, product_name: prod, container_size: sz, price: Number(r.price) });
      }
    }
    const deleted = [...seed.keys()]
      .filter((k) => !present.has(k))
      .map((k) => k.split(SEP));
    if (!changed.length && !deleted.length) return;
    save.mutate(
      { rows: changed, delete: deleted },
      {
        onSuccess: (d) =>
          notifySuccess(`Saved ${d.saved} changed/added · ${d.deleted} deleted.`),
        onError: (e) => notifyError(e),
      },
    );
  }

  return (
    <PageLayout
      title={meta.title}
      description="Review unit-price history and the reference prices that drive the price-anomaly flag on new orders. auto rows refresh from the most recent price actually paid on each extraction sync; an admin editing one makes it a permanent manual override."
      breadcrumbs={meta.breadcrumbs}
      width="form"
    >
      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        {data && (
          <>
            <SectionCard title="Price history" subtitle="Unit price ($)">
              <Group gap="sm" align="flex-end">
                <Select
                  label="Product"
                  size="xs"
                  w={260}
                  data={products}
                  value={product}
                  onChange={(v) => {
                    setProduct(v);
                    setSize(null);
                  }}
                  searchable
                  placeholder="Pick a product"
                />
                <Select
                  label="Size"
                  size="xs"
                  w={140}
                  data={sizes}
                  value={size}
                  onChange={setSize}
                  disabled={!product}
                />
              </Group>
              <HistoryChart product={product} size={size} />
            </SectionCard>

            <SectionCard
              title="Reference prices"
              actions={
                <>
                  <Button size="xs" variant="default" onClick={addRow} disabled={!canAdmin}>
                    Add row
                  </Button>
                  <Button
                    size="xs"
                    onClick={onSave}
                    loading={save.isPending}
                    disabled={!canAdmin}
                  >
                    Save changes
                  </Button>
                </>
              }
            >
              {roleKnown && !canAdmin && (
                <Alert color="gray" variant="light" title="View only" mb="sm">
                  Reference prices are admin-only. You can review the current values and the
                  price history above, but not change them.
                </Alert>
              )}

              <Table.ScrollContainer minWidth={720} type="native">
                <Table striped withTableBorder verticalSpacing={4}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Customer</Table.Th>
                      <Table.Th>Product</Table.Th>
                      <Table.Th>Size</Table.Th>
                      <Table.Th w={130}>Price ($)</Table.Th>
                      <Table.Th w={90}>Source</Table.Th>
                      <Table.Th w={44} />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {rows.map((r) => (
                      <Table.Tr key={r._rk}>
                        <Table.Td>
                          <TextInput
                            size="xs"
                            aria-label="Customer"
                            disabled={!canAdmin}
                            value={r.customer_name}
                            onChange={(e) => patch(r._rk, { customer_name: e.currentTarget.value })}
                          />
                        </Table.Td>
                        <Table.Td>
                          <TextInput
                            size="xs"
                            aria-label="Product"
                            disabled={!canAdmin}
                            value={r.product_name}
                            onChange={(e) => patch(r._rk, { product_name: e.currentTarget.value })}
                          />
                        </Table.Td>
                        <Table.Td>
                          <TextInput
                            size="xs"
                            aria-label="Size"
                            disabled={!canAdmin}
                            value={r.container_size}
                            onChange={(e) => patch(r._rk, { container_size: e.currentTarget.value })}
                          />
                        </Table.Td>
                        <Table.Td>
                          <NumberInput
                            size="xs"
                            aria-label="Price"
                            disabled={!canAdmin}
                            decimalScale={2}
                            value={r.price}
                            onChange={(v) => patch(r._rk, { price: v === "" ? "" : Number(v) })}
                            hideControls
                          />
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs" c={r.source === "manual" ? "gpGreen.7" : "dimmed"}>
                            {r.source}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <ActionIcon
                            size="sm"
                            variant="subtle"
                            color="red"
                            disabled={!canAdmin}
                            onClick={() => removeRow(r._rk)}
                            aria-label="Delete row"
                          >
                            <IconTrash size={15} />
                          </ActionIcon>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </SectionCard>
          </>
        )}
      </QueryBoundary>
    </PageLayout>
  );
}

function buildOption(
  data: PriceHistory,
  delivery: "adj" | "raw",
  preEra: "faded" | "hidden",
  showTrend: boolean,
) {
  if (!data.points.length) return null;
  const band = data.standardization_band;
  const val = (p: PricePoint) => (delivery === "adj" ? p.unit_price_adj : p.unit_price);

  const byCust = new Map<string, PricePoint[]>();
  for (const p of data.points) {
    if (!p.date) continue;
    const c = p.customer_name ?? "—";
    if (!byCust.has(c)) byCust.set(c, []);
    byCust.get(c)!.push(p);
  }

  const series: TimeSeries[] = [];
  for (const [name, pts] of byCust) {
    const post = pts.filter((p) => p.era === "post");
    const pre = pts.filter((p) => p.era === "pre");
    if (post.length) series.push({ name, points: post.map((p) => [p.date!, val(p)]) });
    if (pre.length && preEra === "faded") {
      // bridge the dashed pre-segment to the first solid point so they meet
      const bridged = post.length ? [...pre, post[0]] : pre;
      series.push({ name, variant: "ghost", points: bridged.map((p) => [p.date!, val(p)]) });
    }
  }

  // current reference price(s) — a flat guide line across the standardized era only
  const lastDate = data.points[data.points.length - 1]?.date ?? band.end;
  for (const r of data.reference_prices) {
    series.push({
      name: `${r.customer_name} · ref`,
      variant: "reference",
      points: [
        [band.end, r.price],
        [lastDate, r.price],
      ],
    });
  }

  if (showTrend && data.standardized_trend.length > 1) {
    series.push({
      name: "Standardized-era median",
      variant: "trend",
      points: data.standardized_trend.map((t) => [t.date, t.price]),
    });
  }

  return timeLineOption(series, {
    fmt: "currency2",
    bandX: [band.start, band.end],
    bandLabel: "Pricing standardized",
  });
}

function HistoryChart({ product, size }: { product: string | null; size: string | null }) {
  const { data, isLoading } = usePriceHistory(product, size);
  const [delivery, setDelivery] = useState<"adj" | "raw">("adj");
  const [preEra, setPreEra] = useState<"faded" | "hidden">("faded");
  const [showTrend, setShowTrend] = useState(false);

  const option = useMemo(
    () => (data ? buildOption(data, delivery, preEra, showTrend) : null),
    [data, delivery, preEra, showTrend],
  );

  if (!product || !size)
    return (
      <Text size="sm" c="dimmed">
        Pick a product and size.
      </Text>
    );
  if (isLoading) return <Loader size="sm" />;
  if (!option) return <EmptyState label="No priced history for this selection" compact />;

  return (
    <Stack gap="xs">
      <Group gap="lg" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={delivery}
          onChange={(v) => setDelivery(v as "adj" | "raw")}
          data={[
            { label: "Delivery-adjusted", value: "adj" },
            { label: "Raw", value: "raw" },
          ]}
        />
        <SegmentedControl
          size="xs"
          value={preEra}
          onChange={(v) => setPreEra(v as "faded" | "hidden")}
          data={[
            { label: "Pre-2024 faded", value: "faded" },
            { label: "Pre-2024 hidden", value: "hidden" },
          ]}
        />
        <Switch
          size="xs"
          label="Standardized-era trend"
          checked={showTrend}
          onChange={(e) => setShowTrend(e.currentTarget.checked)}
        />
      </Group>
      <Chart option={option} height={320} />
      <Text size="xs" c="dimmed">
        {delivery === "adj"
          ? "Prices before delivery was itemised in QuickBooks have an estimated per-item delivery fee removed so the trend is comparable end to end."
          : "Unit prices exactly as recorded — a step down where the delivery charge moved to its own QuickBooks line."}
      </Text>
      {data && data.reference_prices.length > 0 && (
        <Text size="xs" c="dimmed">
          Current reference:{" "}
          {data.reference_prices
            .map((r) => `${r.customer_name} ${fmtCurrency(r.price, true)} (${r.source})`)
            .join(" · ")}
        </Text>
      )}
    </Stack>
  );
}
