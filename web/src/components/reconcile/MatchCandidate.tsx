import { Anchor, Badge, Button, Group, Paper, Text, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconExternalLink, IconX } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import type { ReconcileCandidate } from "@/api/reconcile";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { LineDiffTable, DiffSummary } from "./LineDiff";

export function confColor(c: string): string {
  if (c.startsWith("Certain") || c === "High") return "gpGreen";
  if (c === "Medium") return "gpGold";
  return "orange";
}

export const CONF_RANK: Record<string, number> = { Certain: 4, High: 3, Medium: 2, Low: 1 };

function QboLink({ url }: { url: string | null | undefined }) {
  if (!url) return null;
  return (
    <Anchor href={url} target="_blank" rel="noreferrer" size="xs">
      <Group gap={3} wrap="nowrap">
        Open in QuickBooks <IconExternalLink size={11} />
      </Group>
    </Anchor>
  );
}

export function InvoicePoNumber({
  invPoNumber,
  match,
  orderPo,
}: {
  invPoNumber: string | null | undefined;
  match: boolean | null | undefined;
  orderPo: string | null;
}) {
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="xs" c="dimmed">
        Invoice PO#
      </Text>
      <Text size="xs" fw={600} style={NUMERIC_STYLE}>
        {invPoNumber || "—"}
      </Text>
      {match === true && (
        <Badge size="xs" color="gpGreen" variant="light">
          matches order
        </Badge>
      )}
      {match === false && (
        <Badge size="xs" color="red" variant="light">
          ≠ order PO {orderPo ?? "—"}
        </Badge>
      )}
    </Group>
  );
}

export function MatchCandidate({
  c,
  orderPo,
  best,
  canEdit,
  busy,
  onConfirm,
  onReject,
}: {
  c: ReconcileCandidate;
  orderPo: string | null;
  best: boolean;
  canEdit: boolean;
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
}) {
  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      bg="var(--gp-surface)"
      style={best ? { borderColor: "var(--mantine-color-gpGreen-6)", borderWidth: 2 } : undefined}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start" mb={4}>
        <div style={{ minWidth: 0 }}>
          <Group gap={8} wrap="wrap">
            {best && (
              <Badge size="xs" color="gpGreen">
                best match
              </Badge>
            )}
            <Text size="sm" fw={600}>
              Invoice {c.doc_number ?? c.invoice_id}
            </Text>
            <QboLink url={c.qbo_url} />
          </Group>
          <Text size="xs" c="dimmed">
            {c.inv_customer ?? "—"} · {c.txn_date?.slice(0, 10) ?? "—"} ·{" "}
            <span style={NUMERIC_STYLE}>{fmtCurrency(c.total_amt)}</span>
          </Text>
          <Group mt={2}>
            <InvoicePoNumber invPoNumber={c.inv_po_number} match={c.po_number_match} orderPo={orderPo} />
          </Group>
          {c.other_confirmed_po && (
            <Group gap={4} mt={4}>
              <IconAlertTriangle size={13} color="var(--mantine-color-red-6)" />
              <Text size="xs" c="red">
                Already confirmed to{" "}
                <Anchor component={Link} to={`/reconcile/${c.other_confirmed_po.po_id}`} c="red" fw={600}>
                  PO {c.other_confirmed_po.po_number ?? c.other_confirmed_po.po_id}
                </Anchor>{" "}
                — unlink it there first.
              </Text>
            </Group>
          )}
        </div>
        <Badge color={confColor(c.confidence)} variant="light">
          {c.confidence}
        </Badge>
      </Group>

      <DiffSummary diff={c.diff} />
      <LineDiffTable diff={c.diff} />

      <Group mt="sm" gap="xs">
        <Tooltip
          disabled={!c.other_confirmed_po}
          label={`Already confirmed to PO ${c.other_confirmed_po?.po_number ?? c.other_confirmed_po?.po_id} — unlink it there first`}
        >
          <Button
            size="xs"
            variant={best ? "filled" : "light"}
            leftSection={<IconCheck size={14} />}
            onClick={onConfirm}
            loading={busy}
            disabled={!canEdit || !!c.other_confirmed_po}
          >
            Confirm{best ? " match" : ""}
          </Button>
        </Tooltip>
        <Button
          size="xs"
          variant="default"
          color="red"
          leftSection={<IconX size={14} />}
          onClick={onReject}
          loading={busy}
          disabled={!canEdit}
        >
          Not a match
        </Button>
      </Group>
    </Paper>
  );
}
