import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Button,
  Group,
  NumberInput,
  Stack,
  Table,
  TextInput,
  Textarea,
} from "@mantine/core";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useCreatePo, type PoHeader, type PoLineItem } from "@/api/poEdit";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";

const EMPTY: PoLineItem = {
  product_raw: "",
  product_name: "",
  container_size: "",
  quantity: null,
  unit_price: null,
  line_total: null,
  additional_cost: null,
};

export function NewPoPage() {
  const nav = useNavigate();
  const create = useCreatePo();

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  const [items, setItems] = useState<(PoLineItem & { _rk: string })[]>([]);
  const rk = useRef(0);
  const nextRk = () => `r${rk.current++}`;

  const set = (k: keyof PoHeader, v: unknown) => setHeader((h) => ({ ...h, [k]: v }));
  const setItem = (i: number, k: keyof PoLineItem, v: unknown) =>
    setItems((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <PageLayout
      title="New purchase order"
      description="A PO typed in by hand (phone order, walk-in). It is created active and marked edited, so the extraction pipeline never touches it."
      breadcrumbs={[{ label: "Match & Reconcile", to: "/match" }, { label: "New PO" }]}
      width="form"
      actions={
        <Button variant="subtle" onClick={() => nav(-1)}>
          Cancel
        </Button>
      }
    >
      <Stack gap="lg">
        <SectionCard title="Order details">
          <Group grow>
            <TextInput label="PO number" value={header.po_number ?? ""} onChange={(e) => set("po_number", e.currentTarget.value)} />
            <TextInput label="Customer" value={header.customer_name ?? ""} onChange={(e) => set("customer_name", e.currentTarget.value)} />
          </Group>
          <Group grow>
            <TextInput label="PO date" placeholder="YYYY-MM-DD" value={header.po_date ?? ""} onChange={(e) => set("po_date", e.currentTarget.value)} />
            <TextInput label="Delivery date" placeholder="YYYY-MM-DD" value={header.delivery_date ?? ""} onChange={(e) => set("delivery_date", e.currentTarget.value)} />
          </Group>
          <Group grow>
            <NumberInput label="Subtotal" value={header.subtotal ?? undefined} onChange={(v) => set("subtotal", v === "" ? null : Number(v))} decimalScale={2} />
            <NumberInput label="Tax" value={header.tax ?? undefined} onChange={(v) => set("tax", v === "" ? null : Number(v))} decimalScale={2} />
            <NumberInput label="Total" value={header.total ?? undefined} onChange={(v) => set("total", v === "" ? null : Number(v))} decimalScale={2} />
          </Group>
        </SectionCard>

        <SectionCard
          title="Line items"
          actions={
            <Button
              size="xs"
              variant="default"
              leftSection={<IconPlus size={14} />}
              onClick={() => setItems((r) => [...r, { ...EMPTY, _rk: nextRk() }])}
            >
              Add line
            </Button>
          }
        >
          <Table.ScrollContainer minWidth={680} type="native">
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Product</Table.Th>
                  <Table.Th>Size</Table.Th>
                  <Table.Th>Qty</Table.Th>
                  <Table.Th>Unit price</Table.Th>
                  <Table.Th>Adtl. cost</Table.Th>
                  <Table.Th>Line total</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((it, i) => (
                  <Table.Tr key={it._rk}>
                    <Table.Td>
                      <TextInput size="xs" aria-label="Product" value={it.product_name ?? ""} onChange={(e) => setItem(i, "product_name", e.currentTarget.value)} />
                    </Table.Td>
                    <Table.Td w={80}>
                      <TextInput size="xs" aria-label="Size" value={it.container_size ?? ""} onChange={(e) => setItem(i, "container_size", e.currentTarget.value)} />
                    </Table.Td>
                    <Table.Td w={90}>
                      <NumberInput size="xs" aria-label="Quantity" hideControls value={it.quantity ?? undefined} onChange={(v) => setItem(i, "quantity", v === "" ? null : Number(v))} />
                    </Table.Td>
                    <Table.Td w={110}>
                      <NumberInput size="xs" aria-label="Unit price" hideControls decimalScale={2} value={it.unit_price ?? undefined} onChange={(v) => setItem(i, "unit_price", v === "" ? null : Number(v))} />
                    </Table.Td>
                    <Table.Td w={110}>
                      <NumberInput size="xs" aria-label="Additional cost" hideControls decimalScale={2} value={it.additional_cost ?? undefined} onChange={(v) => setItem(i, "additional_cost", v === "" ? null : Number(v))} />
                    </Table.Td>
                    <Table.Td w={110}>
                      <NumberInput size="xs" aria-label="Line total" hideControls decimalScale={2} value={it.line_total ?? undefined} onChange={(v) => setItem(i, "line_total", v === "" ? null : Number(v))} />
                    </Table.Td>
                    <Table.Td w={40}>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label="Remove line"
                        onClick={() => setItems((r) => r.filter((_, j) => j !== i))}
                      >
                        <IconTrash size={15} />
                      </ActionIcon>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>

          <Textarea label="Notes" value={header.notes ?? ""} onChange={(e) => set("notes", e.currentTarget.value)} autosize minRows={2} />

          {create.error && <Alert color="red">{(create.error as Error).message}</Alert>}

          <Group>
            <Button
              loading={create.isPending}
              onClick={() => create.mutate({ header, items }, { onSuccess: (r) => nav(`/po/${r.po_id}`) })}
            >
              Create PO
            </Button>
          </Group>
        </SectionCard>
      </Stack>
    </PageLayout>
  );
}
