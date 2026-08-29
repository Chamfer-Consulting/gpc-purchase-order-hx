import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { usePo, useSavePo, type PoHeader, type PoLineItem } from "@/api/poEdit";

const EMPTY: PoLineItem = {
  product_raw: "",
  product_name: "",
  container_size: "",
  quantity: null,
  unit_price: null,
  line_total: null,
  additional_cost: null,
};

export function EditPoPage() {
  const { id } = useParams();
  const poId = Number(id);
  const { data, isLoading, error } = usePo(poId);
  const save = useSavePo(poId);

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  // Each row carries a stable client key (_rk) so React doesn't reattach an input's
  // state to the wrong line when a middle row is deleted.
  const [items, setItems] = useState<(PoLineItem & { _rk: string })[]>([]);
  const rk = useRef(0);
  const nextRk = () => `r${rk.current++}`;

  useEffect(() => {
    if (data) {
      setHeader(data.header);
      setItems(data.items.map((it) => ({ ...it, _rk: nextRk() })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (isLoading) return <Loader />;
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;
  if (!data) return null;

  const set = (k: keyof PoHeader, v: unknown) => setHeader((h) => ({ ...h, [k]: v }));
  const setItem = (i: number, k: keyof PoLineItem, v: unknown) =>
    setItems((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <Stack gap="md" maw={900}>
      <Group>
        <Title order={2}>Edit PO {data.header.po_number ?? poId}</Title>
        {data.header.edited && <Badge variant="light">edited — protected from sync</Badge>}
      </Group>
      <Text size="xs" c="dimmed">
        {data.header.source_file}
      </Text>

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

      <div style={{ overflowX: "auto" }}>
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
                  <TextInput size="xs" value={it.product_name ?? it.product_raw ?? ""} onChange={(e) => setItem(i, "product_name", e.currentTarget.value)} />
                </Table.Td>
                <Table.Td w={80}>
                  <TextInput size="xs" value={it.container_size ?? ""} onChange={(e) => setItem(i, "container_size", e.currentTarget.value)} />
                </Table.Td>
                <Table.Td w={90}>
                  <NumberInput size="xs" hideControls value={it.quantity ?? undefined} onChange={(v) => setItem(i, "quantity", v === "" ? null : Number(v))} />
                </Table.Td>
                <Table.Td w={110}>
                  <NumberInput size="xs" hideControls decimalScale={2} value={it.unit_price ?? undefined} onChange={(v) => setItem(i, "unit_price", v === "" ? null : Number(v))} />
                </Table.Td>
                <Table.Td w={110}>
                  <NumberInput size="xs" hideControls decimalScale={2} value={it.additional_cost ?? undefined} onChange={(v) => setItem(i, "additional_cost", v === "" ? null : Number(v))} />
                </Table.Td>
                <Table.Td w={110}>
                  <NumberInput size="xs" hideControls decimalScale={2} value={it.line_total ?? undefined} onChange={(v) => setItem(i, "line_total", v === "" ? null : Number(v))} />
                </Table.Td>
                <Table.Td w={40}>
                  <ActionIcon variant="subtle" color="red" onClick={() => setItems((r) => r.filter((_, j) => j !== i))}>
                    ×
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
      <Button size="xs" variant="default" w="fit-content" onClick={() => setItems((r) => [...r, { ...EMPTY, _rk: nextRk() }])}>
        Add line
      </Button>

      <Textarea label="Notes" value={header.notes ?? ""} onChange={(e) => set("notes", e.currentTarget.value)} autosize minRows={2} />

      <Group>
        <Button
          onClick={() =>
            // _rk is a client-only key; the backend's LineItemIn ignores extra fields.
            save.mutate({ header, items, removed_items: data.removed_items })
          }
          loading={save.isPending}
        >
          Save edit
        </Button>
        {save.data && (
          <Text size="sm" c={save.data.math_check_failed ? "red" : "green"}>
            {save.data.math_check_failed
              ? `Saved — math check: ${save.data.math_check_detail}`
              : "Saved. Math checks out."}
          </Text>
        )}
        {save.error && (
          <Text size="sm" c="red">
            {(save.error as Error).message}
          </Text>
        )}
      </Group>
    </Stack>
  );
}
