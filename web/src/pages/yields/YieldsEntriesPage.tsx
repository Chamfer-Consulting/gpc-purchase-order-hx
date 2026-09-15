import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ActionIcon, Badge, Group, Pagination, Select, Table, Text, Tooltip, useComputedColorScheme } from "@mantine/core";
import { IconChevronDown, IconChevronRight, IconNotes, IconPencil, IconTrash } from "@tabler/icons-react";
import {
  useVoidYieldEntry,
  useYieldEntries,
  useYieldMixes,
  useYieldProducts,
  type YieldEntry,
  type YieldUnit,
} from "@/api/yields";
import { colorMapFor } from "@/charts/palette";
import { paletteFor } from "@/charts/theme";
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

interface DateSection {
  date: string;
  groups: EntryGroup[];
}

/** A second, outer grouping tier — a bold date divider above each day's
 *  product/lot groups, so scanning a long list doesn't mean re-reading the
 *  same date on every row. */
function bucketByDate(groups: EntryGroup[]): DateSection[] {
  const map = new Map<string, DateSection>();
  const order: string[] = [];
  for (const g of groups) {
    const date = g.entries[0].harvest_date;
    let s = map.get(date);
    if (!s) {
      s = { date, groups: [] };
      map.set(date, s);
      order.push(date);
    }
    s.groups.push(g);
  }
  return order.map((d) => map.get(d)!);
}

const DAYS_PER_PAGE = 10;

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

/** Reorders a day's groups so products belonging to the same blend/mix
 *  (e.g. "Rainbow Mix" = Broccoli + Kale + Radish + Mustard, via
 *  yield_product_sales_links) sit next to each other — grouping on top of
 *  the color coding below, not just a shared color scattered across
 *  unrelated rows. Relative order within a mix, and among non-mix
 *  products, is otherwise unchanged. */
function clusterByMix(groups: EntryGroup[], mixByProduct: Map<number, string>): EntryGroup[] {
  return groups
    .map((g, i) => ({ g, i, mix: mixByProduct.get(g.entries[0].yield_product_id) ?? null }))
    .sort((a, b) => {
      if (a.mix === b.mix) return a.i - b.i;
      if (a.mix === null) return 1;
      if (b.mix === null) return -1;
      return a.mix < b.mix ? -1 : a.mix > b.mix ? 1 : a.i - b.i;
    })
    .map((x) => x.g);
}

function mixTag(name: string, color: string) {
  return (
    <Tooltip key="mix" label={`Part of the "${name}" mix`}>
      <Group gap={4} wrap="nowrap">
        <span
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: 2,
            backgroundColor: color,
            flexShrink: 0,
          }}
        />
        <Text size="xs" c="dimmed">
          {name}
        </Text>
      </Group>
    </Tooltip>
  );
}

export function YieldsEntriesPage() {
  const products = useYieldProducts();
  const mixes = useYieldMixes();
  const palette = paletteFor(useComputedColorScheme("light"));
  const [productId, setProductId] = useState<string | null>(null);
  const entries = useYieldEntries({
    yield_product_id: productId ? Number(productId) : undefined,
    include_voided: true,
  });
  const voidEntry = useVoidYieldEntry();
  const [editing, setEditing] = useState<YieldEntry | null>(null);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  // Only one harvest day open at a time (an accordion, not independent
  // toggles like the lot groups below it) — defaults to the most recent
  // day with data, and re-defaults there whenever the currently-open one
  // drops out of view (e.g. the product filter changes) rather than on
  // every render, so a deliberate choice to look at an older day sticks.
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const [page, setPage] = useState(1);
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
  // Which mix (if any) each yield product belongs to, and a stable color
  // per mix name (the house categorical palette, same one charts use —
  // colorMapFor assigns by alphabetical order so it's consistent without
  // having to store a color anywhere).
  const mixByProduct = useMemo(() => {
    const m = new Map<number, string>();
    for (const mix of mixes.data ?? []) {
      for (const id of mix.yield_product_ids) if (!m.has(id)) m.set(id, mix.name);
    }
    return m;
  }, [mixes.data]);
  const mixColorMap = useMemo(
    () => colorMapFor((mixes.data ?? []).map((m) => m.name), palette),
    [mixes.data, palette],
  );
  const groups = useMemo(() => groupEntries(entries.data ?? []), [entries.data]);
  const dateSections = useMemo(() => bucketByDate(groups), [groups]);
  // Paginate by distinct harvest day, not by row — a page always shows whole
  // days (never splits one day's entries across two pages).
  const totalPages = Math.max(1, Math.ceil(dateSections.length / DAYS_PER_PAGE));
  const pageSections = dateSections.slice((page - 1) * DAYS_PER_PAGE, page * DAYS_PER_PAGE);

  useEffect(() => {
    setPage(1);
  }, [productId]);
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  // Auto-expand only applies before the user has touched a day, or when
  // the day they had open drops out of view entirely (e.g. a product
  // filter change). It must NOT re-fire just because a deliberate collapse
  // set expandedDate to null — otherwise closing the open day snaps it
  // right back open, since null would otherwise look identical to
  // "nothing auto-expanded yet".
  const hasInteractedRef = useRef(false);
  useEffect(() => {
    if (dateSections.length === 0) return;
    if (!hasInteractedRef.current) {
      setExpandedDate(dateSections[0].date);
    } else if (expandedDate != null && !dateSections.some((s) => s.date === expandedDate)) {
      setExpandedDate(dateSections[0].date);
    }
  }, [dateSections, expandedDate]);

  const toggleDate = (date: string) => {
    hasInteractedRef.current = true;
    setExpandedDate((current) => (current === date ? null : date));
  };

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

  const entryRow = (e: YieldEntry, muted: boolean) => {
    const mixName = mixByProduct.get(e.yield_product_id);
    const mixColor = mixName ? mixColorMap[mixName] : undefined;
    return (
      <Table.Tr
        key={e.id}
        bg={muted ? "var(--gp-surface-sunken)" : undefined}
        style={mixColor ? { borderLeft: `3px solid ${mixColor}` } : undefined}
      >
        <Table.Td>{fmtDateOnly(e.harvest_date)}</Table.Td>
        <Table.Td>
          <Group gap={6} wrap="nowrap">
            {e.product_name}
            {mixName && mixColor && mixTag(mixName, mixColor)}
            {e.notes && (
              <Tooltip label={e.notes} multiline maw={280}>
                <IconNotes size={14} color="var(--mantine-color-gpGreen-6)" aria-label="Has a note" />
              </Tooltip>
            )}
          </Group>
        </Table.Td>
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
  };

  const renderGroup = (g: EntryGroup) => {
    if (g.entries.length === 1) return entryRow(g.entries[0], false);
    const first = g.entries[0];
    const by = harvestedBySummary(g.entries);
    const activeCount = g.entries.filter((e) => !e.voided).length;
    const countLabel =
      activeCount === g.entries.length ? `${activeCount} entries` : `${activeCount} of ${g.entries.length} entries`;
    const open = openGroups.has(g.key);
    const groupHasNotes = g.entries.some((e) => e.notes);
    const mixName = mixByProduct.get(first.yield_product_id);
    const mixColor = mixName ? mixColorMap[mixName] : undefined;
    return (
      <Fragment key={g.key}>
        <Table.Tr
          fw={600}
          bg="var(--mantine-color-gpGreen-light)"
          style={{ cursor: "pointer", ...(mixColor ? { borderLeft: `3px solid ${mixColor}` } : {}) }}
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
              {mixName && mixColor && mixTag(mixName, mixColor)}
              {groupHasNotes && (
                <Tooltip label="One or more entries here has a note — expand to see it" multiline maw={280}>
                  <IconNotes size={14} color="var(--mantine-color-gpGreen-6)" aria-label="Has a note" />
                </Tooltip>
              )}
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
  };

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
                  {pageSections.map((section) => {
                    const dayEntries = section.groups.flatMap((g) => g.entries);
                    const dayActive = dayEntries.filter((e) => !e.voided).length;
                    const dayOpen = expandedDate === section.date;
                    return (
                      <Fragment key={section.date}>
                        <Table.Tr style={{ cursor: "pointer" }} onClick={() => toggleDate(section.date)}>
                          <Table.Td colSpan={8} style={{ borderBottom: "2px solid var(--gp-border)" }} pt="md">
                            <Group gap={8} wrap="nowrap">
                              {dayOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                              <Text fw={700} size="sm">
                                {fmtDateOnly(section.date)}
                              </Text>
                              <Text size="xs" c="dimmed">
                                {dayActive} entr{dayActive === 1 ? "y" : "ies"} · {weightSubtotal(dayEntries)}
                              </Text>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                        {dayOpen && clusterByMix(section.groups, mixByProduct).map((g) => renderGroup(g))}
                      </Fragment>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {totalPages > 1 && (
            <Group justify="center" mt="md">
              <Pagination total={totalPages} value={page} onChange={setPage} size="sm" />
            </Group>
          )}
        </QueryBoundary>
      </SectionCard>

      <EditEntryModal entry={editing} onClose={() => setEditing(null)} />
    </PageLayout>
  );
}
