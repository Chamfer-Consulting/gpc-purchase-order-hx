import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Group,
  ScrollArea,
  Text,
} from "@mantine/core";
import { IconDeviceFloppy, IconExternalLink } from "@tabler/icons-react";
import type { ReconcilePoView } from "@/api/reconcile";
import { useSavePo, useVoidLine, type PoStatus } from "@/api/poEdit";
import { useMe } from "@/api/me";
import type { usePoEditForm } from "@/hooks/usePoEditForm";
import { fmtDateTime } from "@/lib/datetime";
import { fmtCurrency } from "@/lib/format";
import { conflictInfo, errorMessage, isConflict } from "@/lib/errors";
import { promptReason } from "@/lib/modals";
import { notifySuccess } from "@/lib/notify";
import { NUMERIC_STYLE, STATUS_COLOR } from "@/theme/tokens";
import { PoLineItemsEditor } from "@/components/po/PoLineItemsEditor";
import { VerdictPills } from "./VerdictPills";
import type { useExtractionDecision } from "./extraction";

/** ① The order that came in — the source. Email/PDF snapshot, then what we
 *  pulled out of it (editable in place — same editor + math/price/size warnings
 *  as the full PO page and Data Quality's "Review" action, not a separate
 *  read-only view), then the verdict. Read top to bottom. */
export function OrderSource({
  view,
  ext,
  form,
}: {
  view: ReconcilePoView;
  ext: ReturnType<typeof useExtractionDecision>;
  form: ReturnType<typeof usePoEditForm>;
}) {
  const h = view.header;
  const e = view.extraction;
  const status = (h.status ?? "active") as PoStatus;
  const decided = !!(e.verdict || e.revision_of);
  const { canEdit } = useMe();

  const [showSnap, setShowSnap] = useState(!decided);
  useEffect(() => setShowSnap(!decided), [h.id, decided]);

  const save = useSavePo(h.id);
  const voidLine = useVoidLine(h.id);

  function doSave() {
    save.mutate(
      {
        header: form.header,
        items: form.items,
        removed_items: view.removed_items,
        expected_version: form.seededVersion ?? h.lock_version,
      },
      { onSuccess: () => notifySuccess("Saved.") },
    );
  }

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

      {/* What we extracted — editable in place. The warning icon on a line
         flags the same math / price / no-size issues Data Quality's fix
         queue does; fixing it here clears it there too. */}
      <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>
        What we extracted
      </Text>
      <PoLineItemsEditor
        items={form.items}
        onChange={form.setItems}
        makeRow={form.makeRow}
        headerTotal={h.total}
        showVoid
        disabled={!canEdit}
        minWidth={560}
        onVoidLine={(it) => {
          const lineId = it.id as number;
          if (it.voided) {
            voidLine.mutate({
              line_id: lineId,
              voided: false,
              reason: null,
              expected_version: h.lock_version,
            });
          } else {
            promptReason({
              title: "Void this line",
              description: "The line is kept but excluded from totals and reports.",
              label: "Reason (optional)",
              confirmLabel: "Void line",
              confirmColor: "red",
              onSubmit: (reason) =>
                voidLine.mutate({
                  line_id: lineId,
                  voided: true,
                  reason,
                  expected_version: h.lock_version,
                }),
            });
          }
        }}
      />

      {form.serverMovedAhead && (
        <Alert color="orange" variant="light" mt="xs" title="This order changed on the server">
          Someone else saved a newer version while you were editing. Save to overwrite theirs
          (you&apos;ll get a conflict), or discard your changes and reload.
          <Group mt="xs">
            <Button size="xs" variant="light" color="orange" onClick={() => form.reseed(view)}>
              Discard mine & reload
            </Button>
          </Group>
        </Alert>
      )}

      {save.error && isConflict(save.error) ? (
        <Alert color="orange" variant="light" mt="xs" title="This order changed while you were editing">
          {(() => {
            const c = conflictInfo(save.error);
            return (
              <Text size="sm">
                {c.editedBy ? `${c.editedBy} saved a newer version` : "A newer version was saved"}
                {c.editedAt ? ` at ${fmtDateTime(c.editedAt)}` : ""}. Reload to
                pick up their changes, then re-apply yours.
              </Text>
            );
          })()}
          <Button size="xs" mt="xs" variant="light" color="orange" onClick={() => form.reseed(view)}>
            Discard mine & reload
          </Button>
        </Alert>
      ) : save.error ? (
        <Text size="sm" c="red" mt="xs">
          {errorMessage(save.error)}
        </Text>
      ) : null}

      {save.data?.math_check_failed && (
        <Alert color="orange" variant="light" mt="xs" title="Math check">
          {save.data.math_check_detail || "Line items or totals don't reconcile."} — saved anyway.
        </Alert>
      )}

      {form.isDirty && canEdit && (
        <Group justify="flex-end" mt="xs" gap="xs">
          <Text size="xs" c="dimmed" style={{ flex: 1 }}>
            Unsaved changes to the line items
          </Text>
          <Button size="xs" variant="default" onClick={() => form.reseed(view)}>
            Discard
          </Button>
          <Button
            size="xs"
            leftSection={<IconDeviceFloppy size={14} />}
            loading={save.isPending}
            onClick={doSave}
          >
            Save
          </Button>
        </Group>
      )}

      <Box mt="md">
        <VerdictPills ctl={ext} view={view} />
      </Box>
    </Box>
  );
}
