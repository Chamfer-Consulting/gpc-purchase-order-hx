import { Fragment, useMemo, useState } from "react";
import { ActionIcon, Badge, Group, Select, Table, Text, Tooltip } from "@mantine/core";
import { IconChevronDown, IconChevronRight, IconPencil, IconTrash } from "@tabler/icons-react";
import { useVoidYieldEntry, useYieldEntries, useYieldProducts, type YieldEntry, type YieldUnit } from "@/api/yields";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { fmtDateOnly } from "@/lib/datetime";
import { promptReason } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";
import { EditEntryModal } from "./EditEntryModal";

/** Entries that share a product + harvest date + lot code are almost always
 *  the same physical batch split across multiple people/bins (e.g. two
 *  people each harvesting into the same labeled lot with their own weight)
 *  — group them under one subtotal row while keeping every entry visible
 *  and individually editable/voidable underneath. Entries without a lot
 *  code can't be tied to a batch this way, so they're never grouped. */
interface EntryGroup {
  key: string;
  lotCode: string | null;
  entries: YieldEntry[];
}

function groupEntries(entries: YieldEntry[]): EntryGroup[] {
  const map = new Map<string, EntryGroup>();
  const order: string[] = [];
  for (const e of entries) {
    const key = e.lot_code ? `${e.yield_product_id}::${e.harvest_date}::${e.lot_code}` : `solo::${e.id}`;
    let g = map.get(key);
    if (!g) {
      g = { key, lotCode: e.lot_code, entries: [] };
      map.set(key, g);
      order.push(key);
    }
    g.entries.push(e);
  }
  return order.map((k) => map.get(k)!);
}

const UNIT_ORDER: YieldUnit[] = ["lb", "oz", "g"];

function weightSubtotal(entries: YieldEntry[]): string {
  const byUnit = new Map<YieldUnit, number>();
  for (const e of entries) {
    if (e.voided) continue;
    byUnit.set(e.unit, (byUnit.get(e.unit) ?? 0) + e.weight);
  }
  const parts = UNIT_ORDER.filter((u) => byUnit.has(u)).map(
    (u) => `${Math.round(byUnit.get(u)! * 100) / 100} ${u}`,
  );
  return parts.length ? parts.join(" + ") : "—";
}

function sumField(entries: YieldEntry[], field: "tray_count" | "discarded_tray_count"): number {
  return entries.reduce((total, e) => (e.voided ? total : total + e[field]), 0);
}

function harvestedBySummary(entries: YieldEntry[]): { label: string; title: string } {
  const names = Array.from(new Set(entries.map((e) => e.harvested_by).filter(Boolean)));
  if (names.length <= 1) return { label: names[0] ?? "—", title: names[0] ?? "" };
  return { label: `${names.length} people`, title: names.join(", ") };
}

export function YieldsEntriesPage() {
  const products = useYieldProducts();
  const [productId, setProductId] = useState<string | null>(null);
  const entries = useYieldEntries({
    yield_product_id: productId ? Number(productId) : undefined,
    include_voided: true,
  });
  const voidEntry = useVoidYieldEntry();
  const [editing, setEditing] = useState<YieldEntry | null>(null);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const meta = pageMeta("/yields/entries");

  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );
  const groups = useMemo(() => groupEntries(entries.data ?? []), [entries.data]);

  const askVoid = (entry: YieldEntry) => {
    promptReason({
      title: "Void this entry?",
      description: `"${entry.product_name}" (${fmtDateOnly(entry.harvest_date)}) will be removed from reports.`,
      label: "Reason (optional)",
      confirmLabel: "Void entry",
      confirmColor: "red",
      onSubmit: (reason) =>
        voidEntry.mutate(
          { id: entry.id, reason },
          {
            onSuccess: () => notifySuccess("Entry voided."),
            onError: (e) => notifyError(e),
          },
        ),
    });
  };

  const entryRow = (e: YieldEntry, muted: boolean) => (
    <Table.Tr key={e.id} bg={muted ? "var(--gp-surface-sunken)" : undefined}>
      <Table.Td>{fmtDateOnly(e.harvest_date)}</Table.Td>
      <Table.Td>{e.product_name}</Table.Td>
      <Table.Td ta="right">
        {e.weight} {e.unit}
      </Table.Td>
      <Table.Td ta="right">{e.tray_count}</Table.Td>
      <Table.Td ta="right">{e.discarded_tray_count || "—"}</Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {e.product_lot_code_prefix && (
            <Badge size="xs" variant="outline" color="gray">
              {e.product_lot_code_prefix}
            </Badge>
          )}
          {e.lot_code ?? "—"}
        </Group>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {e.harvested_by}
          {e.voided && (
            <Badge size="xs" color="red" variant="light">
              voided
            </Badge>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        {!e.voided && (
          <Group gap={4} wrap="nowrap">
            <ActionIcon size="sm" variant="subtle" onClick={() => setEditing(e)} aria-label="Edit entry">
              <IconPencil size={14} />
            </ActionIcon>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="red"
              onClick={() => askVoid(e)}
              aria-label="Void entry"
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        )}
      </Table.Td>
    </Table.Tr>
  );

  return (
    <PageLayout
      title={meta?.title ?? "Product Yields"}
      description={meta?.description ?? "Harvest log entries from the field kiosk."}
      breadcrumbs={meta?.breadcrumbs}
    >
      <SectionCard
        title="Entries"
        actions={
          <Select
            placeholder="All products"
            data={productOptions}
            value={productId}
            onChange={setProductId}
            searchable
            clearable
            w={220}
          />
        }
      >
        <QueryBoundary loading={entries.isLoading} error={entries.error} onRetry={() => void entries.refetch()}>
          {!entries.data || entries.data.length === 0 ? (
            <EmptyState label="No harvest entries yet" />
          ) : (
            <Table.ScrollContainer minWidth={820} type="native">
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Date</Table.Th>
                    <Table.Th>Product</Table.Th>
                    <Table.Th ta="right">Weight</Table.Th>
                    <Table.Th ta="right">Trays</Table.Th>
                    <Table.Th ta="right">Discarded</Table.Th>
                    <Table.Th>Lot</Table.Th>
                    <Table.Th>Harvested by</Table.Th>
                    <Table.Th w={72} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {groups.map((g) => {
                    if (g.entries.length === 1) return entryRow(g.entries[0], false);
                    const first = g.entries[0];
                    const by = harvestedBySummary(g.entries);
                    const activeCount = g.entries.filter((e) => !e.voided).length;
                    const countLabel =
                      activeCount === g.entries.length ? `${activeCount} entries` : `${activeCount} of ${g.entries.length} entries`;
                    const open = openGroups.has(g.key);
                    return (
                      <Fragment key={g.key}>
                        <Table.Tr
                          fw={600}
                          bg="var(--mantine-color-gpGreen-light)"
                          style={{ cursor: "pointer" }}
                          onClick={() => toggleGroup(g.key)}
                        >
                          <Table.Td>{fmtDateOnly(first.harvest_date)}</Table.Td>
                          <Table.Td>
                            <Group gap={6} wrap="nowrap">
                              {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                              {first.product_name}
                              <Badge size="xs" variant="light" color="gpGreen">
                                {countLabel}
                              </Badge>
                            </Group>
                          </Table.Td>
                          <Table.Td ta="right">{weightSubtotal(g.entries)}</Table.Td>
                          <Table.Td ta="right">{sumField(g.entries, "tray_count")}</Table.Td>
                          <Table.Td ta="right">{sumField(g.entries, "discarded_tray_count") || "—"}</Table.Td>
                          <Table.Td>
                            <Group gap={6} wrap="nowrap">
                              {first.product_lot_code_prefix && (
                                <Badge size="xs" variant="outline" color="gray">
                                  {first.product_lot_code_prefix}
                                </Badge>
                              )}
                              {g.lotCode}
                            </Group>
                          </Table.Td>
                          <Table.Td>
                            <Tooltip label={by.title} disabled={!by.title.includes(",")}>
                              <Text size="sm" fw={600} span>
                                {by.label}
                              </Text>
                            </Tooltip>
                          </Table.Td>
                          <Table.Td />
                        </Table.Tr>
                        {open && g.entries.map((e) => entryRow(e, true))}
                      </Fragment>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </QueryBoundary>
      </SectionCard>

      <EditEntryModal entry={editing} onClose={() => setEditing(null)} />
    </PageLayout>
  );
}
