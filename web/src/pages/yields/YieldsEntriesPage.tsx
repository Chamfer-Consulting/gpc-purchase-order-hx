import { useMemo, useState } from "react";
import { Badge, Button, Group, Select, Stack, Switch, Table, Text, TextInput } from "@mantine/core";
import { useMe } from "@/api/me";
import {
  useCreateYieldProduct,
  useUpdateYieldProduct,
  useYieldEntries,
  useYieldProducts,
  type YieldProduct,
} from "@/api/yields";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { fmtDateOnly } from "@/lib/datetime";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";

/** A small inline "add a harvest product" form — editor/admin only. Full
 *  product management (rename, SKU links) is a later phase; for now this is
 *  just enough to seed the kiosk's product picker and see what's in it. */
function AddProductForm() {
  const create = useCreateYieldProduct();
  const [name, setName] = useState("");

  return (
    <Group align="flex-end" gap="xs">
      <TextInput
        label="Add a harvest product"
        placeholder="e.g. Kale - Curly"
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
        style={{ flex: 1 }}
      />
      <Button
        loading={create.isPending}
        disabled={!name.trim()}
        onClick={() =>
          create.mutate(
            { name: name.trim() },
            {
              onSuccess: () => {
                notifySuccess(`Added "${name.trim()}".`);
                setName("");
              },
              onError: (e) => notifyError(e),
            },
          )
        }
      >
        Add
      </Button>
    </Group>
  );
}

/** Every harvest product — active ones show up on the kiosk's picker; toggle
 *  off to retire one without losing its entry history. */
function ProductList({ products, canEdit }: { products: YieldProduct[]; canEdit: boolean }) {
  const update = useUpdateYieldProduct();

  if (products.length === 0) {
    return <EmptyState label="No harvest products yet" compact />;
  }

  return (
    <Table verticalSpacing="xs">
      <Table.Tbody>
        {products.map((p) => (
          <Table.Tr key={p.id}>
            <Table.Td>
              <Text fw={500} c={p.active ? undefined : "dimmed"}>
                {p.name}
              </Text>
            </Table.Td>
            <Table.Td w={120}>
              {canEdit ? (
                <Switch
                  checked={p.active}
                  label={p.active ? "Active" : "Retired"}
                  onChange={(e) =>
                    update.mutate(
                      { id: p.id, active: e.currentTarget.checked },
                      { onError: (err) => notifyError(err) },
                    )
                  }
                />
              ) : (
                <Badge color={p.active ? "gpGreen" : "gray"} variant="light">
                  {p.active ? "Active" : "Retired"}
                </Badge>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function YieldsEntriesPage() {
  const { canEdit } = useMe();
  const products = useYieldProducts(true);
  const [productId, setProductId] = useState<string | null>(null);
  const entries = useYieldEntries({
    yield_product_id: productId ? Number(productId) : undefined,
  });
  const meta = pageMeta("/yields");

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );

  return (
    <PageLayout
      title={meta?.title ?? "Product Yields"}
      description={meta?.description ?? "Harvest log entries from the field kiosk."}
      breadcrumbs={meta?.breadcrumbs}
    >
      {canEdit && (
        <SectionCard title="Harvest products" subtitle="What the kiosk's product picker offers">
          <Stack gap="md">
            <AddProductForm />
            <QueryBoundary
              loading={products.isLoading}
              error={products.error}
              onRetry={() => void products.refetch()}
            >
              <ProductList products={products.data ?? []} canEdit={canEdit} />
            </QueryBoundary>
          </Stack>
        </SectionCard>
      )}

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
            <Table.ScrollContainer minWidth={760} type="native">
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Date</Table.Th>
                    <Table.Th>Product</Table.Th>
                    <Table.Th ta="right">Weight</Table.Th>
                    <Table.Th ta="right">Trays</Table.Th>
                    <Table.Th ta="right">Discarded</Table.Th>
                    <Table.Th>Bin</Table.Th>
                    <Table.Th>Lot</Table.Th>
                    <Table.Th>Harvested by</Table.Th>
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
                      <Table.Td>{e.storage_bin ?? "—"}</Table.Td>
                      <Table.Td>{e.lot_code ?? "—"}</Table.Td>
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
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </QueryBoundary>
      </SectionCard>
    </PageLayout>
  );
}
