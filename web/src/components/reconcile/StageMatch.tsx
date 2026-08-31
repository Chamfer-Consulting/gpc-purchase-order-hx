import { useState } from "react";
import {
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import type { ReconcileCandidate, ReconcilePoView } from "@/api/reconcile";
import { useConfirmBatch, useReconcileConfirm, useReconcileReject } from "@/api/reconcile";
import { useInvoiceSearch } from "@/api/poEdit";
import { useManualLink } from "@/api/matching";
import { useMe } from "@/api/me";
import { fmtCurrency } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { LineDiffTable, DiffSummary } from "./LineDiff";

function confColor(c: string): string {
  if (c.startsWith("Certain") || c === "High") return "gpGreen";
  if (c === "Medium") return "gpGold";
  return "orange";
}

function CandidateCard({
  c,
  canEdit,
  onConfirm,
  onReject,
  busy,
}: {
  c: ReconcileCandidate;
  canEdit: boolean;
  onConfirm: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  return (
    <Paper withBorder radius="md" p="md" bg="var(--gp-surface)">
      <Group justify="space-between" wrap="nowrap" mb={6}>
        <div>
          <Text size="sm" fw={600}>
            Invoice {c.doc_number ?? c.invoice_id}
          </Text>
          <Text size="xs" c="dimmed">
            {c.inv_customer ?? "—"} · {c.txn_date?.slice(0, 10) ?? "—"} ·{" "}
            <span style={NUMERIC_STYLE}>{fmtCurrency(c.total_amt)}</span>
          </Text>
        </div>
        <Badge color={confColor(c.confidence)} variant="light">
          {c.confidence}
        </Badge>
      </Group>

      <DiffSummary diff={c.diff} />
      <LineDiffTable diff={c.diff} />

      <Group mt="sm" gap="xs">
        <Button
          size="xs"
          leftSection={<IconCheck size={14} />}
          onClick={onConfirm}
          loading={busy}
          disabled={!canEdit}
        >
          Confirm match
        </Button>
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

export function StageMatch({ view }: { view: ReconcilePoView }) {
  const { canEdit, roleKnown } = useMe();
  const poId = view.header.id;
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();
  const batch = useConfirmBatch();
  const manual = useManualLink();
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);

  const cands = view.candidates;
  const links = view.links.filter((l) => l.confirmed);
  const quick = cands.filter((c) => c.quick);

  const doConfirm = (invoice_id: number) =>
    confirm.mutate({ po_id: poId, invoice_id }, { onSuccess: () => notifySuccess("Match confirmed.") });
  const doReject = (invoice_id: number) => reject.mutate({ po_id: poId, invoice_id });

  const busy = confirm.isPending || reject.isPending || batch.isPending;

  return (
    <SectionCard
      title="3 · Match"
      subtitle="Which QuickBooks invoice backs this order?"
      actions={
        quick.length >= 2 && (
          <Button
            size="xs"
            variant="light"
            disabled={!canEdit}
            loading={batch.isPending}
            onClick={() =>
              batch.mutate(
                quick.map((c) => ({ po_id: poId, invoice_id: c.invoice_id })),
                { onSuccess: () => notifySuccess(`Confirmed ${quick.length} high-confidence matches.`) },
              )
            }
          >
            Confirm {quick.length} high-confidence
          </Button>
        )
      }
    >
      {links.length > 0 && (
        <Stack gap={6}>
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            Confirmed
          </Text>
          {links.map((l) => (
            <Paper key={l.invoice_id} withBorder radius="sm" p="sm" bg="var(--mantine-color-gpGreen-light)">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">
                  Invoice {l.doc_number ?? l.invoice_id} · {l.match_method} ·{" "}
                  <span style={NUMERIC_STYLE}>{fmtCurrency(l.total_amt)}</span>
                </Text>
                {l.diff && <DiffSummary diff={l.diff} />}
              </Group>
            </Paper>
          ))}
        </Stack>
      )}

      {cands.length === 0 && links.length === 0 && (
        <EmptyState
          title="No candidates"
          description="Run matching after a QuickBooks sync, or link an invoice by hand below."
        />
      )}

      <Stack gap="md">
        {cands.map((c) => (
          <CandidateCard
            key={c.invoice_id}
            c={c}
            canEdit={canEdit}
            busy={busy}
            onConfirm={() => doConfirm(c.invoice_id)}
            onReject={() => doReject(c.invoice_id)}
          />
        ))}
      </Stack>

      <Divider label="Link an invoice by hand" labelPosition="left" />
      <TextInput
        size="xs"
        placeholder="invoice number or customer"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        disabled={!canEdit}
      />
      {hits.data && hits.data.length > 0 && (
        <Table fz="xs" verticalSpacing={4}>
          <Table.Tbody>
            {hits.data.map((h) => (
              <Table.Tr key={h.invoice_id}>
                <Table.Td>{h.doc_number ?? h.invoice_id}</Table.Td>
                <Table.Td>{h.customer_name}</Table.Td>
                <Table.Td>{h.txn_date}</Table.Td>
                <Table.Td style={NUMERIC_STYLE}>
                  {h.total_amt != null ? fmtCurrency(h.total_amt) : "—"}
                </Table.Td>
                <Table.Td>
                  {h.linked && (
                    <Badge size="xs" color="gray" variant="light" mr="xs">
                      linked
                    </Badge>
                  )}
                  <Button
                    size="xs"
                    variant="light"
                    disabled={!canEdit}
                    loading={manual.isPending}
                    onClick={() =>
                      manual.mutate(
                        { po_id: poId, invoice_id: h.invoice_id },
                        { onSuccess: () => notifySuccess("Linked.") },
                      )
                    }
                  >
                    Link
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {roleKnown && !canEdit && (
        <Text size="xs" c="dimmed">
          Confirming, rejecting or linking needs the editor role.
        </Text>
      )}
    </SectionCard>
  );
}
