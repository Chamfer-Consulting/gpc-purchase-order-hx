import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useAuth } from "@/auth/AuthProvider";
import { useVoidYieldEntry, useYieldEntries } from "@/api/yields";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { promptReason } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Today's entries submitted from this kiosk account — self-service correction
 *  for a mis-entered harvest. The backend only allows voiding a same-day, own
 *  entry for the 'field' role, so this deliberately only shows today's rows. */
export function MyRecentEntriesPage() {
  const { session } = useAuth();
  const email = session?.user.email ?? "";
  const { data, isLoading, error, refetch } = useYieldEntries({
    submitted_by: email,
    date_from: today(),
    date_to: today(),
  });
  const voidEntry = useVoidYieldEntry();

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
      <div>
        <Text fw={700} fz={22}>
          Today's entries
        </Text>
        <Text size="sm" c="dimmed">
          Everything logged from this device today. Made a mistake? Void it and log it again.
        </Text>
      </div>

      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        {!data || data.length === 0 ? (
          <EmptyState label="Nothing logged yet today" />
        ) : (
          <Stack gap="sm">
            {data.map((e) => (
              <Card key={e.id} withBorder radius="md" p="md" bg="var(--gp-surface)">
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <div>
                    <Text fw={650}>{e.product_name}</Text>
                    <Text size="sm" c="dimmed">
                      {e.weight} {e.unit} · {e.tray_count} tray{e.tray_count === 1 ? "" : "s"}
                      {e.discarded_tray_count > 0 && ` · ${e.discarded_tray_count} discarded`}
                    </Text>
                    <Group gap={6} mt={4}>
                      {e.storage_bin && (
                        <Badge size="sm" variant="light" color="gray">
                          {e.storage_bin}
                        </Badge>
                      )}
                      {e.lot_code && (
                        <Badge size="sm" variant="light" color="gray">
                          Lot {e.lot_code}
                        </Badge>
                      )}
                      <Badge size="sm" variant="light" color="gpGreen">
                        {e.harvested_by}
                      </Badge>
                    </Group>
                  </div>
                  <Button
                    size="xs"
                    color="red"
                    variant="subtle"
                    leftSection={<IconTrash size={14} />}
                    onClick={() => askVoid(e.id, e.product_name)}
                  >
                    Void
                  </Button>
                </Group>
              </Card>
            ))}
          </Stack>
        )}
      </QueryBoundary>
    </Stack>
  );
}
