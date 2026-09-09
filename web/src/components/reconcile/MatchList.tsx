import { useMemo, useState } from "react";
import {
  Anchor,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
import type { LineDiff, ReconcilePoView } from "@/api/reconcile";
import { useConfirmBatch, useReconcileConfirm, useReconcileReject } from "@/api/reconcile";
import { useInvoiceSearch, useLinkInvoice, useUnlinkInvoice, type PoLink } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { fmtCurrency } from "@/lib/format";
import { fmtDateOnly } from "@/lib/datetime";
import { notifySuccess } from "@/lib/notify";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { EmptyState } from "@/components/EmptyState";
import { DiffSummary, LineDiffTable } from "./LineDiff";
import { CONF_RANK, InvoicePoNumber, MatchCandidate } from "./MatchCandidate";

type MatchedLink = PoLink & {
  diff?: LineDiff;
  inv_po_number?: string | null;
  po_number_match?: boolean | null;
};

/** A confirmed PO⇄invoice link. Keeps the full line-by-line PO vs invoice
 *  comparison visible (collapsible) after confirming — the same `LineDiffTable`
 *  a pending candidate shows, so confirming a match doesn't hide the detail you
 *  used to decide it. Open by default when it's the sole match or the lines
 *  don't cleanly reconcile (the case you most want to keep looking at);
 *  collapsed by default for extra clean matches on a multi-invoice PO. */
function MatchedInvoice({
  l,
  orderPo,
  canEdit,
  soleMatch,
  onUnlink,
  unlinking,
}: {
  l: MatchedLink;
  orderPo: string | null;
  canEdit: boolean;
  soleMatch: boolean;
  onUnlink: () => void;
  unlinking: boolean;
}) {
  const [open, setOpen] = useState(soleMatch || (l.diff ? !l.diff.clean : false));

  return (
    <Paper withBorder radius="md" p="md" bg="var(--mantine-color-gpGreen-light)">
      <Group justify="space-between" wrap="wrap" align="flex-start">
        <div style={{ minWidth: 0 }}>
          <Group gap={8} wrap="wrap">
            <Text size="sm" fw={600}>
              Invoice {l.doc_number ?? l.invoice_id}
            </Text>
            <Badge size="xs" variant="light" color="gpGreen">
              {l.match_method}
            </Badge>
            {l.qbo_url && (
              <Anchor href={l.qbo_url} target="_blank" rel="noreferrer" size="xs">
                <Group gap={3} wrap="nowrap">
                  Open in QuickBooks <IconExternalLink size={11} />
                </Group>
              </Anchor>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {l.customer_name ?? "—"} · {l.txn_date ? fmtDateOnly(l.txn_date) : "—"} ·{" "}
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
          loading={unlinking}
          onClick={onUnlink}
        >
          Unlink
        </Button>
      </Group>

      {l.diff && l.diff.rows.length > 0 && (
        <>
          <Button
            size="compact-xs"
            variant="subtle"
            mt="xs"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Hide line detail" : "Show line detail"}
          </Button>
          <Collapse in={open}>
            <div style={{ marginTop: 8 }}>
              <LineDiffTable diff={l.diff} />
            </div>
          </Collapse>
        </>
      )}
    </Paper>
  );
}

/** ③ Potential invoices — below the source. Best-first, confirm one. Also the
 *  one invoice-linking UI in the app — EditPoPage's "Invoice links" section
 *  renders this exact component (no separate plain table + search there
 *  anymore), so confirming, unlinking, and manually searching-and-linking work
 *  identically everywhere. The confirmed match(es) stay visible AND the search
 *  box stays available below them — a PO can legitimately carry more than one
 *  confirmed invoice (partial shipments), so linking isn't a one-shot, hidden-
 *  once-matched action. */
export function MatchList({ view }: { view: ReconcilePoView }) {
  const { canEdit, roleKnown } = useMe();
  const poId = view.header.id;
  const orderPo = view.header.po_number;
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();
  const batch = useConfirmBatch();
  const unlink = useUnlinkInvoice(poId);
  const link = useLinkInvoice(poId);
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

  return (
    <Stack gap="sm">
      {links.length > 0 && (
        <>
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            Matched
          </Text>
          {links.map((l) => (
            <MatchedInvoice
              key={l.invoice_id}
              l={l}
              orderPo={orderPo}
              canEdit={canEdit}
              soleMatch={links.length === 1}
              unlinking={unlink.isPending}
              onUnlink={() =>
                unlink.mutate(l.invoice_id, { onSuccess: () => notifySuccess("Unlinked.") })
              }
            />
          ))}
        </>
      )}

      {links.length === 0 && (
        <>
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
        </>
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
                    loading={link.isPending}
                    onClick={() =>
                      link.mutate(
                        { invoice_id: h.invoice_id },
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
