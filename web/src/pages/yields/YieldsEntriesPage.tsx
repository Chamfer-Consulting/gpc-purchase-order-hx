import { useMemo, useState } from "react";
import { ActionIcon, Badge, Group, Select, Table } from "@mantine/core";
import { IconPencil, IconTrash } from "@tabler/icons-react";
import { useVoidYieldEntry, useYieldEntries, useYieldProducts, type YieldEntry } from "@/api/yields";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { fmtDateOnly } from "@/lib/datetime";
import { promptReason } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";
import { EditEntryModal } from "./EditEntryModal";

export function YieldsEntriesPage() {
  const products = useYieldProducts();
  const [productId, setProductId] = useState<string | null>(null);
  const entries = useYieldEntries({
    yield_product_id: productId ? Number(productId) : undefined,
  });
  const voidEntry = useVoidYieldEntry();
  const [editing, setEditing] = useState<YieldEntry | null>(null);
  const meta = pageMeta("/yields/entries");

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );

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
                  {entries.data.map((e) => (
                    <Table.Tr key={e.id}>
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
                            <ActionIcon
                              size="sm"
                              variant="subtle"
                              onClick={() => setEditing(e)}
                              aria-label="Edit entry"
                            >
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
                  ))}
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
