import { useMemo, useState } from "react";
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
import type { ReconcilePoView } from "@/api/reconcile";
import { useConfirmBatch, useReconcileConfirm, useReconcileReject } from "@/api/reconcile";
import { useInvoiceSearch, useUnlinkInvoice } from "@/api/poEdit";
import { useManualLink } from "@/api/matching";
import { useMe } from "@/api/me";
import { fmtCurrency } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { EmptyState } from "@/components/EmptyState";
import { DiffSummary } from "./LineDiff";
import { CONF_RANK, InvoicePoNumber, MatchCandidate } from "./MatchCandidate";

/** ③ Potential invoices — below the source. Best-first, confirm one. */
export function MatchList({ view }: { view: ReconcilePoView }) {
  const { canEdit, roleKnown } = useMe();
  const poId = view.header.id;
  const orderPo = view.header.po_number;
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();
  const batch = useConfirmBatch();
  const unlink = useUnlinkInvoice(poId);
  const manual = useManualLink();
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);

  const links = view.links.filter((l) => l.confirmed);
  const cands = useMemo(
    () =>
      [...view.candidates].sort(
        (a, b) =>
          (CONF_RANK[b.confidence] ?? 0) - (CONF_RANK[a.confidence] ?? 0) ||
          (b.match_score ?? 0) - (a.match_score ?? 0),
      ),
    [view.candidates],
  );
  const quick = cands.filter((c) => c.quick);
  const busy = confirm.isPending || reject.isPending;

  const doConfirm = (invoice_id: number) =>
    confirm.mutate({ po_id: poId, invoice_id }, { onSuccess: () => notifySuccess("Match confirmed.") });

  // already matched — show the link, offer to undo
  if (links.length > 0) {
    return (
      <Stack gap="sm">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Matched
        </Text>
        {links.map((l) => (
          <Paper key={l.invoice_id} withBorder radius="md" p="md" bg="var(--mantine-color-gpGreen-light)">
            <Group justify="space-between" wrap="wrap" align="flex-start">
              <div>
                <Text size="sm" fw={600}>
                  Invoice {l.doc_number ?? l.invoice_id} · {l.match_method} ·{" "}
                  <span style={NUMERIC_STYLE}>{fmtCurrency(l.total_amt)}</span>
                </Text>
                <Group mt={2}>
                  <InvoicePoNumber invPoNumber={l.inv_po_number} match={l.po_number_match} orderPo={orderPo} />
                </Group>
                {l.diff && (
                  <Group mt={4}>
                    <DiffSummary diff={l.diff} />
                  </Group>
                )}
              </div>
              <Button
                size="xs"
                variant="subtle"
                color="red"
                disabled={!canEdit}
                loading={unlink.isPending}
                onClick={() =>
                  unlink.mutate(l.invoice_id, { onSuccess: () => notifySuccess("Unlinked.") })
                }
              >
                Unlink
              </Button>
            </Group>
          </Paper>
        ))}
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Potential invoices{cands.length ? ` (${cands.length})` : ""}
        </Text>
        {quick.length >= 2 && (
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
        )}
      </Group>

      {cands.length === 0 ? (
        <EmptyState
          title="No candidates"
          description="Run matching after a QuickBooks sync, or search for an invoice below."
        />
      ) : (
        cands.map((c, i) => (
          <MatchCandidate
            key={c.invoice_id}
            c={c}
            orderPo={orderPo}
            best={i === 0 && cands.length > 1}
            canEdit={canEdit}
            busy={busy}
            onConfirm={() => doConfirm(c.invoice_id)}
            onReject={() => reject.mutate({ po_id: poId, invoice_id: c.invoice_id })}
          />
        ))
      )}

      <Divider label="Search QuickBooks" labelPosition="left" mt="xs" />
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
                <Table.Td ta="right" style={NUMERIC_STYLE}>
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
    </Stack>
  );
}
