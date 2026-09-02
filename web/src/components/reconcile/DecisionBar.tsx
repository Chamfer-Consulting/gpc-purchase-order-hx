import { Link } from "react-router-dom";
import { Anchor, Badge, Button, Group, Paper, SegmentedControl, Stack, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import type { ReconcilePoView, Stage } from "@/api/reconcile";
import { useConfirmBatch, useReconcileConfirm, useReconcileReject } from "@/api/reconcile";
import { useMe } from "@/api/me";
import { fmtCurrency } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { NUMERIC_STYLE, STATUS_COLOR } from "@/theme/tokens";
import type { PoStatus } from "@/api/poEdit";
import { StageStepper } from "./StageStepper";
import { RevisionOfInput, type Verdict } from "./StageExtraction";
import type { StageState } from "./state";

interface ExtCtl {
  verdict: Verdict;
  setVerdict: (v: Verdict) => void;
  revisionOf: string;
  setRevisionOf: (v: string) => void;
  save: (v?: Verdict, revOf?: string) => void;
  saving: boolean;
}

export function DecisionBar({
  view,
  poId,
  focus,
  states,
  onFocus,
  onSkip,
  ext,
}: {
  view: ReconcilePoView;
  poId: number;
  focus: Stage;
  states: Record<Stage, StageState>;
  onFocus: (s: Stage) => void;
  onSkip: () => void;
  ext: ExtCtl;
}) {
  const { canEdit } = useMe();
  const h = view.header;
  const status = (h.status ?? "active") as PoStatus;
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();
  const batch = useConfirmBatch();
  const quick = view.candidates.filter((c) => c.quick);
  const top = view.candidates[0];

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      bg="var(--gp-surface)"
      style={{ position: "sticky", top: 8, zIndex: 4 }}
    >
      <Stack gap={8}>
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs" wrap="wrap" style={{ minWidth: 0 }}>
            <Text fw={700}>PO {h.po_number ?? poId}</Text>
            <Text size="sm" c="dimmed" truncate maw={220}>
              {h.customer_name ?? "—"}
            </Text>
            <Text size="sm" c="dimmed" style={NUMERIC_STYLE}>
              {fmtCurrency(h.total)}
            </Text>
            {status !== "active" && (
              <Badge size="xs" color={STATUS_COLOR[status]} variant="filled">
                {status}
              </Badge>
            )}
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Anchor component={Link} to={`/po/${poId}`} size="sm">
              Full editor ↗
            </Anchor>
            <Button size="xs" variant="default" onClick={onSkip}>
              Skip →
            </Button>
          </Group>
        </Group>

        <StageStepper states={states} focus={focus} onFocus={onFocus} />

        {focus === "extraction" && (
          <Group gap="sm" align="flex-end" wrap="wrap">
            <SegmentedControl
              size="xs"
              value={ext.verdict}
              onChange={(v) => ext.setVerdict(v as Verdict)}
              disabled={!canEdit}
              data={[
                { value: "is_po", label: "Looks right" },
                { value: "not_po", label: "Not a PO" },
                { value: "needs_fix", label: "Needs fix" },
                { value: "revision", label: "Revision of…" },
              ]}
            />
            {ext.verdict === "revision" && (
              <RevisionOfInput
                view={view}
                value={ext.revisionOf}
                onChange={ext.setRevisionOf}
                disabled={!canEdit}
              />
            )}
            <Button size="xs" onClick={() => ext.save()} loading={ext.saving} disabled={!canEdit}>
              Save →
            </Button>
            {ext.verdict === "needs_fix" && (
              <Button size="xs" variant="light" component={Link} to={`/po/${poId}`}>
                Open editor
              </Button>
            )}
          </Group>
        )}

        {focus === "match" &&
          (top ? (
            <Group gap="sm" wrap="wrap">
              <Text size="xs" c="dimmed">
                Top: Invoice {top.doc_number ?? top.invoice_id} · {top.confidence}
              </Text>
              <Button
                size="xs"
                leftSection={<IconCheck size={14} />}
                disabled={!canEdit}
                loading={confirm.isPending}
                onClick={() =>
                  confirm.mutate(
                    { po_id: poId, invoice_id: top.invoice_id },
                    { onSuccess: () => notifySuccess("Match confirmed.") },
                  )
                }
              >
                Confirm {top.doc_number ?? top.invoice_id}
              </Button>
              <Button
                size="xs"
                variant="default"
                color="red"
                leftSection={<IconX size={14} />}
                disabled={!canEdit}
                loading={reject.isPending}
                onClick={() => reject.mutate({ po_id: poId, invoice_id: top.invoice_id })}
              >
                Not a match
              </Button>
              {quick.length >= 2 && (
                <Button
                  size="xs"
                  variant="light"
                  disabled={!canEdit}
                  loading={batch.isPending}
                  onClick={() =>
                    batch.mutate(
                      quick.map((c) => ({ po_id: poId, invoice_id: c.invoice_id })),
                      {
                        onSuccess: () =>
                          notifySuccess(`Confirmed ${quick.length} high-confidence matches.`),
                      },
                    )
                  }
                >
                  Confirm {quick.length} high-confidence
                </Button>
              )}
            </Group>
          ) : (
            <Text size="xs" c="dimmed">
              No candidates — link an invoice by hand below.
            </Text>
          ))}

        {focus === "lifecycle" && (
          <Text size="xs" c="dimmed">
            Change the order's status below.
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
