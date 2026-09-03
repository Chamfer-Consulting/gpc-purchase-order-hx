import { useEffect, useState } from "react";
import { Alert, Button, Collapse, Group, Select, Stack, Text, TextInput, UnstyledButton } from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import type { ReconcilePoView } from "@/api/reconcile";
import { useSetStatus, type PoStatus } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { STATUS_COLOR } from "@/theme/tokens";
import { transitionOptions } from "@/lib/poStatus";
import { notifySuccess } from "@/lib/notify";

/** ④ Lifecycle — a foot-of-card disclosure. Rarely the reason you're here. */
export function LifecycleDisclosure({ view }: { view: ReconcilePoView }) {
  const { canAdmin, roleKnown } = useMe();
  const poId = view.header.id;
  const current = (view.header.status ?? "active") as PoStatus;
  const setStatus = useSetStatus(poId);

  const [open, setOpen] = useState(current !== "active");
  const [target, setTarget] = useState<PoStatus>(current);
  const [reason, setReason] = useState(view.header.status_reason ?? "");
  const [confirmReactivate, setConfirmReactivate] = useState(false);

  useEffect(() => {
    setTarget(current);
    setReason(view.header.status_reason ?? "");
    setConfirmReactivate(false);
    setOpen(current !== "active");
  }, [current, view.header.status_reason, poId]);

  const reactivating = current !== "active" && target === "active";
  const unchanged = target === current && reason === (view.header.status_reason ?? "");

  function apply() {
    setStatus.mutate(
      { status: target, reason: reason || null, expected_version: view.header.lock_version },
      { onSuccess: () => { notifySuccess(`Status set to ${target}.`); setConfirmReactivate(false); } },
    );
  }

  return (
    <div>
      <UnstyledButton onClick={() => setOpen((o) => !o)} py={4}>
        <Group gap={6}>
          <IconChevronRight
            size={14}
            style={{ transform: open ? "rotate(90deg)" : undefined, transition: "transform 120ms" }}
          />
          <Text size="sm" c="dimmed">
            Order is{" "}
            <Text span c={STATUS_COLOR[current]} fw={600}>
              {current}
            </Text>
            {view.header.status_reason ? ` — ${view.header.status_reason}` : ""} · change status
          </Text>
        </Group>
      </UnstyledButton>

      <Collapse in={open}>
        <Stack gap="sm" pt="xs">
          {current !== "active" && (
            <Alert color={STATUS_COLOR[current]} variant="light" p="xs">
              A <b>{current}</b> order is hidden from every report and skipped by the pipeline.
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
                  Bringing a <b>{current}</b> order back to <b>active</b> returns it to every report,
                  the review queue, and invoice matching. It stays marked <b>edited</b>.
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
      </Collapse>
    </div>
  );
}
