import { useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  CloseButton,
  Collapse,
  Group,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPencil,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useMe } from "@/api/me";
import {
  useCreateYieldLink,
  useCreateYieldProduct,
  useDeleteYieldLink,
  useDeleteYieldProduct,
  useUpdateYieldProduct,
  useYieldLinks,
  useYieldProducts,
  useYieldSalesProductNames,
  type YieldProduct,
} from "@/api/yields";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { confirmAction } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";

/** A small inline "add a harvest product" form — editor/admin only. */
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

/** A product's sales-SKU links — one row can feed several sold SKUs (sold
 *  fresh + in a blend), and a blend SKU pulls from several yield products, so
 *  this is a genuine many-to-many, not a "pick one" mapping. */
function ProductLinks({ productId }: { productId: number }) {
  const links = useYieldLinks(productId);
  const salesNames = useYieldSalesProductNames();
  const create = useCreateYieldLink();
  const del = useDeleteYieldLink();
  const [selected, setSelected] = useState<string | null>(null);

  const linkedNames = new Set((links.data ?? []).map((l) => l.sales_product_name));
  const salesOptions = (salesNames.data ?? []).filter((n) => !linkedNames.has(n));

  return (
    <Stack gap="xs" py="sm" pl="md">
      <QueryBoundary loading={links.isLoading} error={links.error} onRetry={() => void links.refetch()}>
        <Group gap={6} wrap="wrap">
          {(links.data ?? []).length === 0 && (
            <Text size="xs" c="dimmed">
              Not linked to any sales SKU yet.
            </Text>
          )}
          {(links.data ?? []).map((l) => (
            <Badge
              key={l.id}
              variant="light"
              color="gray"
              rightSection={
                <CloseButton
                  size={12}
                  onClick={() => del.mutate(l.id, { onError: (e) => notifyError(e) })}
                  aria-label={`Unlink ${l.sales_product_name}`}
                />
              }
            >
              {l.sales_product_name}
            </Badge>
          ))}
        </Group>
      </QueryBoundary>
      <Group gap="xs">
        <Select
          placeholder="Link a sales SKU…"
          data={salesOptions}
          value={selected}
          onChange={setSelected}
          searchable
          size="xs"
          w={280}
          disabled={salesNames.isLoading}
        />
        <Button
          size="xs"
          variant="light"
          disabled={!selected}
          loading={create.isPending}
          onClick={() =>
            selected &&
            create.mutate(
              { yield_product_id: productId, sales_product_name: selected },
              { onSuccess: () => setSelected(null), onError: (e) => notifyError(e) },
            )
          }
        >
          Link
        </Button>
      </Group>
    </Stack>
  );
}

function ProductRow({ product, canEdit }: { product: YieldProduct; canEdit: boolean }) {
  const update = useUpdateYieldProduct();
  const del = useDeleteYieldProduct();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(product.name);
  const [linksOpen, setLinksOpen] = useState(false);

  const cancelEdit = () => {
    setEditing(false);
    setName(product.name);
  };

  const saveName = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === product.name) {
      cancelEdit();
      return;
    }
    update.mutate(
      { id: product.id, name: trimmed },
      {
        onSuccess: () => {
          notifySuccess("Renamed.");
          setEditing(false);
        },
        onError: (e) => {
          notifyError(e);
          setName(product.name);
        },
      },
    );
  };

  const askDelete = () => {
    confirmAction({
      title: "Delete this product?",
      body: `"${product.name}" will be permanently removed. This only works if no harvest entries reference it yet — if any exist, retire it instead of deleting it.`,
      confirmLabel: "Delete",
      onConfirm: () =>
        del.mutate(product.id, {
          onSuccess: () => notifySuccess("Deleted."),
          onError: (e) => notifyError(e),
        }),
    });
  };

  return (
    <>
      <Table.Tr>
        {canEdit && (
          <Table.Td w={32}>
            <ActionIcon
              size="sm"
              variant="subtle"
              onClick={() => setLinksOpen((v) => !v)}
              aria-label="Sales SKU links"
            >
              {linksOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            </ActionIcon>
          </Table.Td>
        )}
        <Table.Td>
          {editing ? (
            <Group gap={4} wrap="nowrap">
              <TextInput
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                size="xs"
                data-autofocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") cancelEdit();
                }}
              />
              <ActionIcon size="sm" color="gpGreen" variant="light" onClick={saveName} loading={update.isPending}>
                <IconCheck size={14} />
              </ActionIcon>
              <ActionIcon size="sm" variant="subtle" onClick={cancelEdit}>
                <IconX size={14} />
              </ActionIcon>
            </Group>
          ) : (
            <Text fw={500} c={product.active ? undefined : "dimmed"}>
              {product.name}
            </Text>
          )}
        </Table.Td>
        <Table.Td w={120}>
          {canEdit ? (
            <Switch
              checked={product.active}
              label={product.active ? "Active" : "Retired"}
              onChange={(e) =>
                update.mutate(
                  { id: product.id, active: e.currentTarget.checked },
                  { onError: (err) => notifyError(err) },
                )
              }
            />
          ) : (
            <Badge color={product.active ? "gpGreen" : "gray"} variant="light">
              {product.active ? "Active" : "Retired"}
            </Badge>
          )}
        </Table.Td>
        {canEdit && (
          <Table.Td w={72}>
            {!editing && (
              <Group gap={4} wrap="nowrap">
                <ActionIcon size="sm" variant="subtle" onClick={() => setEditing(true)} aria-label="Rename">
                  <IconPencil size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  onClick={askDelete}
                  loading={del.isPending}
                  aria-label="Delete"
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            )}
          </Table.Td>
        )}
      </Table.Tr>
      {canEdit && (
        <Table.Tr>
          <Table.Td colSpan={4} p={0}>
            <Collapse in={linksOpen}>
              <ProductLinks productId={product.id} />
            </Collapse>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
}

/** Every harvest product — active ones show up on the kiosk's picker; retire
 *  (toggle off) to hide one from the picker without losing its entry
 *  history, or delete it outright while it still has zero entries. Expand a
 *  row (editor/admin only) to manage its sales-SKU links. */
function ProductList({ products, canEdit }: { products: YieldProduct[]; canEdit: boolean }) {
  if (products.length === 0) {
    return <EmptyState label="No harvest products yet" compact />;
  }

  return (
    <Table verticalSpacing="xs">
      <Table.Tbody>
        {products.map((p) => (
          <ProductRow key={p.id} product={p} canEdit={canEdit} />
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function YieldsAdminPage() {
  const { canEdit } = useMe();
  const products = useYieldProducts(true);
  const meta = pageMeta("/yields/admin");

  return (
    <PageLayout
      title={meta?.title ?? "Harvest products"}
      description={meta?.description ?? "Manage the kiosk's product catalog and its sales-SKU links."}
      breadcrumbs={meta?.breadcrumbs}
      width="form"
    >
      <SectionCard
        title="Harvest products"
        subtitle="What the kiosk's product picker offers. Expand a row to link it to the sales SKU(s) it's sold as."
      >
        <Stack gap="md">
          {canEdit && <AddProductForm />}
          <QueryBoundary
            loading={products.isLoading}
            error={products.error}
            onRetry={() => void products.refetch()}
          >
            <ProductList products={products.data ?? []} canEdit={canEdit} />
          </QueryBoundary>
        </Stack>
      </SectionCard>
    </PageLayout>
  );
}
