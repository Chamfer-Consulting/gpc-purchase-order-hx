import { useState } from "react";
import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import { IconPencil, IconTrash } from "@tabler/icons-react";
import { useAuth } from "@/auth/AuthProvider";
import { useVoidYieldEntry, useYieldEntries, type YieldEntry } from "@/api/yields";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { businessToday } from "@/lib/datetime";
import { promptReason } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
import { EditEntryModal } from "./EditEntryModal";

/** Today's entries submitted from this kiosk account — self-service correction
 *  for a mis-entered harvest. The backend only allows voiding a same-day, own
 *  entry for the 'field' role, so this deliberately only shows today's rows —
 *  "today" is the business's own calendar day (businessToday), matching the
 *  backend's business_now().date() gate, not this device's local clock. */
export function MyRecentEntriesPage() {
  const { session } = useAuth();
  const email = session?.user.email ?? "";
  const { data, isLoading, error, refetch } = useYieldEntries(
    {
      submitted_by: email,
      date_from: businessToday(),
      date_to: businessToday(),
    },
    // apiGet drops an empty-string param entirely, which would turn a
    // not-yet-resolved session into an *unfiltered* fetch of every kiosk's
    // entries for today instead of matching nothing — wait for a real email.
    { enabled: !!email },
  );
  const voidEntry = useVoidYieldEntry();
  const [editing, setEditing] = useState<YieldEntry | null>(null);

  const askVoid = (id: number, label: string) => {
    promptReason({
      title: "Void this entry?",
      description: `"${label}" will be removed from reports. This can't be undone from the kiosk.`,
      label: "Reason (optional)",
      confirmLabel: "Void entry",
      confirmColor: "red",
      onSubmit: (reason) =>
        voidEntry.mutate(
          { id, reason },
          {
            onSuccess: () => notifySuccess("Entry voided."),
            onError: (e) => notifyError(e),
          },
        ),
    });
  };

  return (
    <Stack gap="lg">
      {/* No page title here — the kiosk shell's tab bar already reads
       *  "Recent entries" for the active tab, and every line saved here is
       *  one more the no-scroll shell doesn't have to fit a scrollbar for. */}
      <Text size="sm" c="dimmed">
        Everything logged from this device today. Made a mistake? Void it and log it again.
      </Text>

      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        {!data || data.length === 0 ? (
          <EmptyState label="Nothing logged yet today" />
        ) : (
          <Stack gap="md">
            {data.map((e) => (
              <Card key={e.id} withBorder radius="md" p="lg" bg="var(--gp-surface)">
                <Group justify="space-between" align="flex-start" wrap="wrap" gap="md">
                  <div>
                    <Text fw={650} fz="lg">
                      {e.product_name}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {e.weight} {e.unit} · {e.tray_count} tray{e.tray_count === 1 ? "" : "s"}
                      {e.discarded_tray_count > 0 && ` · ${e.discarded_tray_count} discarded`}
                    </Text>
                    <Group gap={6} mt={4}>
                      {e.lot_code && (
                        <Badge size="sm" variant="light" color="gray">
                          {e.product_lot_code_prefix && `${e.product_lot_code_prefix} · `}
                          Lot {e.lot_code}
                        </Badge>
                      )}
                      <Badge size="sm" variant="light" color="gpGreen">
                        {e.harvested_by}
                      </Badge>
                    </Group>
                  </div>
                  <Group gap="sm" wrap="nowrap">
                    <Button
                      size="md"
                      variant="light"
                      leftSection={<IconPencil size={16} />}
                      onClick={() => setEditing(e)}
                    >
                      Edit
                    </Button>
                    <Button
                      size="md"
                      color="red"
                      variant="light"
                      leftSection={<IconTrash size={16} />}
                      onClick={() => askVoid(e.id, e.product_name)}
                    >
                      Void
                    </Button>
                  </Group>
                </Group>
              </Card>
            ))}
          </Stack>
        )}
      </QueryBoundary>

      <EditEntryModal entry={editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}
