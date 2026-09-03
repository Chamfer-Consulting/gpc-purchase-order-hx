import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Group,
  ScrollArea,
  Table,
  Text,
} from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
import type { ReconcilePoView } from "@/api/reconcile";
import type { PoStatus } from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE, STATUS_COLOR } from "@/theme/tokens";
import { VerdictPills } from "./VerdictPills";
import type { useExtractionDecision } from "./extraction";

/** ① The order that came in — the source. Email/PDF snapshot, then what we
 *  pulled out of it, then the verdict. Read top to bottom. */
export function OrderSource({
  view,
  ext,
}: {
  view: ReconcilePoView;
  ext: ReturnType<typeof useExtractionDecision>;
}) {
  const h = view.header;
  const e = view.extraction;
  const status = (h.status ?? "active") as PoStatus;
  const decided = !!(e.verdict || e.revision_of);

  const [showSnap, setShowSnap] = useState(!decided);
  useEffect(() => setShowSnap(!decided), [h.id, decided]);

  return (
    <Box>
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="xs" wrap="wrap" style={{ minWidth: 0 }}>
          <Text fw={700} fz="lg">
            PO {h.po_number ?? h.id}
          </Text>
          <Text c="dimmed" truncate maw={260}>
            {h.customer_name ?? "—"}
          </Text>
          <Text c="dimmed" style={NUMERIC_STYLE}>
            {fmtCurrency(h.total)}
          </Text>
          {h.po_date && (
            <Text c="dimmed" size="sm">
              {h.po_date}
            </Text>
          )}
          {status !== "active" && (
            <Badge size="sm" color={STATUS_COLOR[status]} variant="filled">
              {status}
            </Badge>
          )}
        </Group>
        <Anchor component={Link} to={`/po/${h.id}`} size="sm">
          Open full editor ↗
        </Anchor>
      </Group>

      <Divider my="sm" />

      {/* What the customer sent */}
      <Group justify="space-between" mb={4}>
        <Group gap="xs">
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            What the customer sent
          </Text>
          {e.gmail_url && (
            <Anchor href={e.gmail_url} target="_blank" rel="noreferrer" size="xs">
              <Group gap={3}>
                Open Gmail thread <IconExternalLink size={11} />
              </Group>
            </Anchor>
          )}
        </Group>
        {e.snapshot && (
          <Button size="compact-xs" variant="subtle" onClick={() => setShowSnap((s) => !s)}>
            {showSnap ? "Hide" : "Show"}
          </Button>
        )}
      </Group>
      {e.subject && (
        <Text size="sm" fw={500} mb={4}>
          {e.subject}
        </Text>
      )}
      {e.snapshot ? (
        showSnap && (
          <ScrollArea.Autosize mah={420} mb="md">
            <Code block fz={11}>
              {e.snapshot}
            </Code>
          </ScrollArea.Autosize>
        )
      ) : (
        <Text size="sm" c="dimmed" mb="md">
          No stored extraction snapshot for this order.
        </Text>
      )}

      {/* What we extracted */}
      <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>
        What we extracted
      </Text>
      <Table fz="xs" verticalSpacing={3} withRowBorders mb="md">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Product</Table.Th>
            <Table.Th ta="right">Qty</Table.Th>
            <Table.Th ta="right">Line total</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {view.items.map((it, i) => (
            <Table.Tr key={i}>
              <Table.Td>
                {it.product_name ?? it.product_raw ?? "?"}
                {it.container_size ? ` · ${it.container_size}` : ""}
              </Table.Td>
              <Table.Td ta="right" style={NUMERIC_STYLE}>
                {it.quantity ?? "—"}
              </Table.Td>
              <Table.Td ta="right" style={NUMERIC_STYLE}>
                {fmtCurrency(it.line_total, true)}
              </Table.Td>
            </Table.Tr>
          ))}
          {view.items.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={3}>
                <Text size="xs" c="dimmed">
                  No line items extracted.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>

      <VerdictPills ctl={ext} view={view} />
    </Box>
  );
}
