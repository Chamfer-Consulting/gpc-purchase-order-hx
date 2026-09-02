import { useEffect, useState } from "react";
import { Alert, Button, Group, Select, Stack, Text, TextInput } from "@mantine/core";
import type { ReconcilePoView } from "@/api/reconcile";
import { useSetStatus, type PoStatus } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { STATUS_COLOR } from "@/theme/tokens";
import { transitionOptions } from "@/lib/poStatus";
import { notifySuccess } from "@/lib/notify";

/** Should this order count — or is it cancelled / withdrawn / a duplicate?
 *  Never a queue blocker; reached from the tracker when a person wants to change
 *  the status. */
export function LifecycleBody({ view }: { view: ReconcilePoView }) {
  const { canAdmin, roleKnown } = useMe();
  const poId = view.header.id;
  const current = (view.header.status ?? "active") as PoStatus;
  const setStatus = useSetStatus(poId);

  const [target, setTarget] = useState<PoStatus>(current);
  const [reason, setReason] = useState(view.header.status_reason ?? "");
  const [confirmReactivate, setConfirmReactivate] = useState(false);

  useEffect(() => {
    setTarget(current);
    setReason(view.header.status_reason ?? "");
    setConfirmReactivate(false);
  }, [current, view.header.status_reason, poId]);

  const reactivating = current !== "active" && target === "active";
  const unchanged = target === current && reason === (view.header.status_reason ?? "");

  function apply() {
    setStatus.mutate(
      { status: target, reason: reason || null, expected_version: view.header.lock_version },
      {
        onSuccess: () => {
          notifySuccess(`Status set to ${target}.`);
          setConfirmReactivate(false);
        },
      },
    );
  }

  return (
    <Stack gap="sm">
      {current !== "active" && (
        <Alert color={STATUS_COLOR[current]} variant="light">
          This order is <b>{current}</b>
          {view.header.status_reason ? ` — ${view.header.status_reason}` : ""}. It's hidden from every
          report and skipped by the pipeline.
        </Alert>
      )}

      <Group align="flex-end" gap="sm" wrap="wrap">
        <Select
          label="Status"
          size="xs"
          w={150}
          data={transitionOptions(current)}
          value={target}
          onChange={(v) => v && setTarget(v as PoStatus)}
          disabled={!canAdmin}
        />
        <TextInput
          label="Reason"
          size="xs"
          style={{ flex: 1, minWidth: 180 }}
          placeholder="kept on the audit trail"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
          disabled={!canAdmin}
        />
        <Button
          size="xs"
          variant="light"
          loading={setStatus.isPending}
          disabled={!canAdmin || unchanged}
          onClick={() => (reactivating ? setConfirmReactivate(true) : apply())}
        >
          Apply
        </Button>
      </Group>

      {confirmReactivate && (
        <Alert color="orange" variant="light" title={`Reactivate PO ${view.header.po_number ?? poId}?`}>
          <Stack gap="xs">
            <Text size="sm">
              Bringing a <b>{current}</b> order back to <b>active</b> returns it to every report and
              revenue total, the review queue, and invoice matching. It stays marked <b>edited</b>.
            </Text>
            <Group>
              <Button size="xs" color="orange" loading={setStatus.isPending} onClick={apply}>
                Reactivate order
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setConfirmReactivate(false)}>
                Keep it {current}
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}

      {roleKnown && !canAdmin && (
        <Text size="xs" c="dimmed">
          Changing lifecycle status needs the admin role.
        </Text>
      )}
    </Stack>
  );
}
