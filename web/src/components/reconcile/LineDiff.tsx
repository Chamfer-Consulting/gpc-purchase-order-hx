import { Badge, Group, Table, Text } from "@mantine/core";
import type { LineDiff, LineDiffRow, LineDiffStatus } from "@/api/reconcile";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { EmptyState } from "@/components/EmptyState";

const STATUS_META: Record<LineDiffStatus, { label: string; bg: string; badge: string }> = {
  match: { label: "match", bg: "transparent", badge: "gray" },
  qty_diff: { label: "qty differs", bg: "var(--mantine-color-orange-light)", badge: "orange" },
  price_diff: { label: "price differs", bg: "var(--mantine-color-yellow-light)", badge: "gpGold" },
  total_diff: { label: "total differs", bg: "var(--mantine-color-orange-light)", badge: "orange" },
  po_only: { label: "not on invoice", bg: "var(--mantine-color-blue-light)", badge: "blue" },
  inv_only: { label: "extra on invoice", bg: "var(--mantine-color-blue-light)", badge: "blue" },
};

const num = (v: number | null | undefined) =>
  v == null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(2);

function Cell({ side }: { side: LineDiffRow["po"] }) {
  if (!side)
    return (
      <Text size="xs" c="dimmed">
        —
      </Text>
    );
  return (
    <Text size="xs" style={NUMERIC_STYLE}>
      {num(side.quantity)} × {fmtCurrency(side.unit_price, true)} = {fmtCurrency(side.line_total, true)}
    </Text>
  );
}

export function LineDiffTable({ diff }: { diff: LineDiff }) {
  if (!diff.rows.length) return <EmptyState label="No line items on either side" compact />;

  return (
    <Table.ScrollContainer minWidth={520} type="native">
      <Table verticalSpacing={4} fz="xs" withRowBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Product</Table.Th>
            <Table.Th>Purchase order</Table.Th>
            <Table.Th>Invoice</Table.Th>
            <Table.Th ta="right">Δ total</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {diff.rows.map((r, i) => {
            const meta = STATUS_META[r.status];
            return (
              <Table.Tr key={i} style={{ background: meta.bg }}>
                <Table.Td>
                  <Text size="xs" fw={500}>
                    {r.product ?? "?"}
                    {r.size ? ` · ${r.size}` : ""}
                  </Text>
                  {r.status !== "match" && (
                    <Badge size="xs" variant="light" color={meta.badge}>
                      {meta.label}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Cell side={r.po} />
                </Table.Td>
                <Table.Td>
                  <Cell side={r.inv} />
                </Table.Td>
                <Table.Td ta="right" style={NUMERIC_STYLE}>
                  {r.deltas.line_total == null || r.deltas.line_total === 0
                    ? "—"
                    : fmtCurrency(r.deltas.line_total, true)}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
        <Table.Tfoot>
          <Table.Tr>
            <Table.Th>Totals</Table.Th>
            <Table.Th style={NUMERIC_STYLE}>{fmtCurrency(diff.totals.po)}</Table.Th>
            <Table.Th style={NUMERIC_STYLE}>{fmtCurrency(diff.totals.inv)}</Table.Th>
            <Table.Th ta="right" style={NUMERIC_STYLE}>
              <Text
                size="xs"
                fw={700}
                c={Math.abs(diff.totals.delta) > 0.02 ? "orange" : "dimmed"}
              >
                {diff.totals.delta === 0 ? "—" : fmtCurrency(diff.totals.delta)}
              </Text>
            </Table.Th>
          </Table.Tr>
        </Table.Tfoot>
      </Table>
    </Table.ScrollContainer>
  );
}

export function DiffSummary({ diff }: { diff: LineDiff }) {
  return (
    <Group gap="xs">
      {diff.clean ? (
        <Badge color="gpGreen" variant="light" size="sm">
          lines match
        </Badge>
      ) : (
        <Badge color="orange" variant="light" size="sm">
          {diff.n_diff} of {diff.n_rows} line{diff.n_rows === 1 ? "" : "s"} differ
        </Badge>
      )}
      <Text size="xs" c={Math.abs(diff.totals.delta) > 0.02 ? "orange" : "dimmed"} style={NUMERIC_STYLE}>
        total Δ {diff.totals.delta === 0 ? "$0" : fmtCurrency(diff.totals.delta)}
      </Text>
    </Group>
  );
}
