import { useMemo, useState } from "react";
import { ActionIcon, Alert, Autocomplete, Badge, Button, Group, Paper, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useMe } from "@/api/me";
import { useCreateYieldNote, useDeleteYieldNote, useYieldEntries, useYieldNotes } from "@/api/yields";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { businessDaysAgo, businessToday, fmtDateOnly } from "@/lib/datetime";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";

/** A note ties to a specific lot_code by default (the traceability case) —
 *  leave it blank for a general note not specific to any one lot. */
function AddNoteForm() {
  // A rolling 60-day window of recent entries, just to seed lot-code
  // suggestions — not a full history view.
  const recent = useYieldEntries({ date_from: businessDaysAgo(60) });
  const create = useCreateYieldNote();
  const [lotCode, setLotCode] = useState("");
  const [date, setDate] = useState(businessToday());
  const [note, setNote] = useState("");

  const lotSuggestions = useMemo(
    () => Array.from(new Set((recent.data ?? []).map((e) => e.lot_code).filter((v): v is string => Boolean(v)))).sort(),
    [recent.data],
  );

  const submit = () => {
    if (!note.trim()) return;
    create.mutate(
      { lot_code: lotCode.trim() || null, note: note.trim(), note_date: date },
      {
        onSuccess: () => {
          notifySuccess("Note added.");
          setNote("");
        },
        onError: (e) => notifyError(e),
      },
    );
  };

  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap" align="flex-end">
        <Autocomplete
          label="Lot code"
          description="Leave blank for a general note, not tied to one lot"
          placeholder="e.g. TK0911"
          data={lotSuggestions}
          value={lotCode}
          onChange={setLotCode}
          w={240}
        />
        <TextInput type="date" label="Date" value={date} onChange={(e) => setDate(e.currentTarget.value)} w={160} />
      </Group>
      <Textarea
        placeholder="Growing conditions, pest pressure, a change worth remembering…"
        value={note}
        onChange={(e) => setNote(e.currentTarget.value)}
        autosize
        minRows={2}
      />
      <Group justify="flex-end">
        <Button disabled={!note.trim()} loading={create.isPending} onClick={submit}>
          Add note
        </Button>
      </Group>
    </Stack>
  );
}

export function YieldsNotesPage() {
  const meta = pageMeta("/yields/notes");
  const { canAdmin, roleKnown } = useMe();
  const notes = useYieldNotes();
  const del = useDeleteYieldNote();

  if (roleKnown && !canAdmin) {
    return (
      <PageLayout
        title={meta?.title ?? "Notes"}
        description={meta?.description}
        breadcrumbs={meta?.breadcrumbs}
      >
        <Alert color="gray" variant="light" title="Admin access required">
          Grower notes are only available to admins for now.
        </Alert>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      title={meta?.title ?? "Notes"}
      description={meta?.description ?? "Freeform growing observations, not tied to a specific harvest."}
      breadcrumbs={meta?.breadcrumbs}
      width="form"
    >
      <SectionCard title="Add a note">
        <AddNoteForm />
      </SectionCard>

      <SectionCard title="Recent notes">
        <QueryBoundary loading={notes.isLoading} error={notes.error} onRetry={() => void notes.refetch()}>
          {!notes.data || notes.data.length === 0 ? (
            <EmptyState label="No notes yet" compact />
          ) : (
            <Stack gap="xs">
              {notes.data.map((n) => (
                <Paper key={n.id} withBorder radius="md" p="sm" bg="var(--gp-surface)">
                  <Group justify="space-between" align="flex-start" wrap="nowrap">
                    <div style={{ minWidth: 0 }}>
                      <Group gap={6} mb={4}>
                        <Text size="xs" c="dimmed">
                          {fmtDateOnly(n.note_date)}
                        </Text>
                        {n.lot_code ? (
                          <Badge size="xs" variant="light" color="gpGreen">
                            {n.lot_code}
                          </Badge>
                        ) : (
                          <Badge size="xs" variant="light" color="gray">
                            General
                          </Badge>
                        )}
                        <Text size="xs" c="dimmed">
                          · {n.submitted_by}
                        </Text>
                      </Group>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                        {n.note}
                      </Text>
                    </div>
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="red"
                      onClick={() =>
                        del.mutate(n.id, {
                          onSuccess: () => notifySuccess("Deleted."),
                          onError: (e) => notifyError(e),
                        })
                      }
                      aria-label="Delete note"
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Paper>
              ))}
            </Stack>
          )}
        </QueryBoundary>
      </SectionCard>
    </PageLayout>
  );
}
