import { ActionIcon, Button, Group, NumberInput, Table, Text, TextInput, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconBan, IconCopy, IconPlus, IconTrash } from "@tabler/icons-react";
import type { PoLineItem } from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_INPUT_STYLES, NUMERIC_STYLE } from "@/theme/tokens";

export type EditableLine = PoLineItem & { _rk: string };

export const EMPTY_LINE: PoLineItem = {
  product_raw: "",
  product_name: "",
  container_size: "",
  quantity: null,
  unit_price: null,
  line_total: null,
  additional_cost: null,
};

const n = (v: unknown): number | null => {
  const x = typeof v === "number" ? v : v === "" || v == null ? null : Number(v);
  return x == null || Number.isNaN(x) ? null : x;
};

/** qty × unit_price + additional_cost, or null if any input is missing. */
export function expectedLineTotal(it: PoLineItem): number | null {
  const q = n(it.quantity);
  const p = n(it.unit_price);
  if (q == null || p == null) return null;
  return q * p + (n(it.additional_cost) ?? 0);
}

export function lineMathOff(it: PoLineItem): string | null {
  if (it.voided) return null;
  const exp = expectedLineTotal(it);
  const lt = n(it.line_total);
  if (exp == null || lt == null) return null;
  if (Math.abs(exp - lt) <= 0.02) return null;
  const addl = n(it.additional_cost);
  return addl
    ? `${it.quantity} × ${fmtCurrency(n(it.unit_price), true)} + ${fmtCurrency(addl, true)} = ${fmtCurrency(exp, true)}, not ${fmtCurrency(lt, true)}`
    : `${it.quantity} × ${fmtCurrency(n(it.unit_price), true)} = ${fmtCurrency(exp, true)}, not ${fmtCurrency(lt, true)}`;
}

export function sumLineTotals(items: PoLineItem[]): number {
  return items.reduce((s, it) => (it.voided ? s : s + (n(it.line_total) ?? 0)), 0);
}

interface Props {
  items: EditableLine[];
  onChange: (items: EditableLine[]) => void;
  /** parent owns the _rk counter so two editors never collide */
  makeRow: (seed?: Partial<PoLineItem>) => EditableLine;
  /** compare Σ line_total against this (the header total) in the footer */
  headerTotal?: number | null;
  showVoid?: boolean;
  onVoidLine?: (line: EditableLine) => void;
  disabled?: boolean;
  minWidth?: number;
}

export function PoLineItemsEditor({
  items,
  onChange,
  makeRow,
  headerTotal,
  showVoid = false,
  onVoidLine,
  disabled = false,
  minWidth = 760,
}: Props) {
  const patch = (i: number, k: keyof PoLineItem, v: unknown) =>
    onChange(items.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const removeAt = (i: number) => onChange(items.filter((_, j) => j !== i));
  const addRow = () => onChange([...items, makeRow()]);
  const duplicate = (i: number) => {
    const { _rk: _drop, id: _dropId, ...rest } = items[i];
    onChange([...items.slice(0, i + 1), makeRow(rest), ...items.slice(i + 1)]);
  };

  const onLastRowEnter = (e: React.KeyboardEvent, i: number) => {
    if (e.key === "Enter" && i === items.length - 1 && !disabled) {
      e.preventDefault();
      addRow();
    }
  };

  const sum = sumLineTotals(items);
  const delta = headerTotal == null ? null : sum - headerTotal;

  return (
    <>
      <Table.ScrollContainer minWidth={minWidth} type="native">
        <Table verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Product</Table.Th>
              <Table.Th>Size</Table.Th>
              <Table.Th ta="right">Qty</Table.Th>
              <Table.Th ta="right">Unit price</Table.Th>
              <Table.Th ta="right">Adtl. cost</Table.Th>
              <Table.Th ta="right">Line total</Table.Th>
              {showVoid && <Table.Th>Void</Table.Th>}
              <Table.Th />
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((it, i) => {
              const off = lineMathOff(it);
              const cell = it.voided
                ? { style: { opacity: 0.45, textDecoration: "line-through" as const } }
                : {};
              return (
                <Table.Tr key={it._rk} onKeyDown={(e) => onLastRowEnter(e, i)}>
                  <Table.Td w={22}>
                    {off && (
                      <Tooltip label={off} multiline w={260}>
                        <IconAlertTriangle size={14} color="var(--gp-status-warning)" />
                      </Tooltip>
                    )}
                  </Table.Td>
                  <Table.Td {...cell}>
                    <TextInput
                      size="xs"
                      aria-label="Product"
                      disabled={disabled}
                      value={it.product_name ?? it.product_raw ?? ""}
                      onChange={(e) => patch(i, "product_name", e.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td w={90} {...cell}>
                    <TextInput
                      size="xs"
                      aria-label="Size"
                      disabled={disabled}
                      value={it.container_size ?? ""}
                      onChange={(e) => patch(i, "container_size", e.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td w={90} {...cell}>
                    <NumberInput
                      size="xs"
                      aria-label="Quantity"
                      hideControls
                      styles={NUMERIC_INPUT_STYLES}
                      disabled={disabled}
                      value={it.quantity ?? undefined}
                      onChange={(v) => patch(i, "quantity", v === "" ? null : Number(v))}
                    />
                  </Table.Td>
                  <Table.Td w={110} {...cell}>
                    <NumberInput
                      size="xs"
                      aria-label="Unit price"
                      hideControls
                      decimalScale={2}
                      styles={NUMERIC_INPUT_STYLES}
                      disabled={disabled}
                      value={it.unit_price ?? undefined}
                      onChange={(v) => patch(i, "unit_price", v === "" ? null : Number(v))}
                    />
                  </Table.Td>
                  <Table.Td w={110} {...cell}>
                    <NumberInput
                      size="xs"
                      aria-label="Additional cost"
                      hideControls
                      decimalScale={2}
                      styles={NUMERIC_INPUT_STYLES}
                      disabled={disabled}
                      value={it.additional_cost ?? undefined}
                      onChange={(v) => patch(i, "additional_cost", v === "" ? null : Number(v))}
                    />
                  </Table.Td>
                  <Table.Td w={120} {...cell}>
                    <NumberInput
                      size="xs"
                      aria-label="Line total"
                      hideControls
                      decimalScale={2}
                      styles={NUMERIC_INPUT_STYLES}
                      disabled={disabled}
                      value={it.line_total ?? undefined}
                      onChange={(v) => patch(i, "line_total", v === "" ? null : Number(v))}
                    />
                  </Table.Td>
                  {showVoid && (
                    <Table.Td w={54}>
                      {it.id && onVoidLine ? (
                        <Tooltip label={it.voided ? "Un-void" : "Void this line"}>
                          <ActionIcon
                            size="sm"
                            variant={it.voided ? "filled" : "subtle"}
                            color={it.voided ? "red" : "gray"}
                            aria-label={it.voided ? "Un-void line" : "Void line"}
                            disabled={disabled}
                            onClick={() => onVoidLine(it)}
                          >
                            <IconBan size={14} />
                          </ActionIcon>
                        </Tooltip>
                      ) : null}
                    </Table.Td>
                  )}
                  <Table.Td w={30}>
                    <Tooltip label="Duplicate row">
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        aria-label="Duplicate line"
                        disabled={disabled}
                        onClick={() => duplicate(i)}
                      >
                        <IconCopy size={14} />
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td w={30}>
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="red"
                      aria-label="Remove line"
                      disabled={disabled}
                      onClick={() => removeAt(i)}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
          <Table.Tfoot>
            <Table.Tr>
              <Table.Th colSpan={showVoid ? 6 : 6} ta="right">
                Σ line totals
              </Table.Th>
              <Table.Th ta="right" style={NUMERIC_STYLE}>
                {fmtCurrency(sum, true)}
              </Table.Th>
              <Table.Th colSpan={showVoid ? 3 : 2}>
                {delta != null && Math.abs(delta) > 0.02 && (
                  <Text size="xs" c="orange" style={NUMERIC_STYLE}>
                    Δ header total {fmtCurrency(delta, true)}
                  </Text>
                )}
              </Table.Th>
            </Table.Tr>
          </Table.Tfoot>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between">
        <Button
          size="xs"
          variant="default"
          leftSection={<IconPlus size={14} />}
          disabled={disabled}
          onClick={addRow}
        >
          Add line
        </Button>
        <Text size="xs" c="dimmed">
          Enter on the last row also adds one
        </Text>
      </Group>
    </>
  );
}
