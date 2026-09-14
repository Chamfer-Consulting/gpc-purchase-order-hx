import { useMemo, useState } from "react";
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconPencil, IconTrash } from "@tabler/icons-react";
import { useMe } from "@/api/me";
import { useCreateYieldNote, useDeleteYieldNote, useYieldEntries, useYieldNotes, type YieldEntry } from "@/api/yields";
import { EmptyState } from "@/components/EmptyState";
import { QueryBoundary } from "@/components/ErrorState";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { businessDaysAgo, businessToday, fmtDateOnly } from "@/lib/datetime";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";
import { EditEntryModal } from "./EditEntryModal";

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

/** A single feed item is either a manually-added grower note, or a harvest
 *  entry's own free-text `notes` field — the latter never showed up here
 *  before, only inside that one entry's edit modal. Deleting only makes
 *  sense for a real note row; an entry-derived item gets an "edit the
 *  entry" action instead, via the same EditEntryModal the Entries table
 *  uses. */
type FeedItem =
  | { kind: "note"; id: number; date: string; lotCode: string | null; submittedBy: string; text: string }
  | {
      kind: "entry";
      entry: YieldEntry;
      date: string;
      lotCode: string | null;
      submittedBy: string;
      text: string;
      productName: string;
    };

export function YieldsNotesPage() {
  const meta = pageMeta("/yields/notes");
  const { canAdmin, roleKnown } = useMe();
  const notes = useYieldNotes();
  const entryNotes = useYieldEntries({ has_notes: true });
  const del = useDeleteYieldNote();
  const [editingEntry, setEditingEntry] = useState<YieldEntry | null>(null);

  const feed = useMemo<FeedItem[]>(() => {
    const noteItems: FeedItem[] = (notes.data ?? []).map((n) => ({
      kind: "note",
      id: n.id,
      date: n.note_date,
      lotCode: n.lot_code,
      submittedBy: n.submitted_by,
      text: n.note,
    }));
    const entryItems: FeedItem[] = (entryNotes.data ?? []).map((e) => ({
      kind: "entry",
      entry: e,
      date: e.harvest_date,
      lotCode: e.lot_code,
      submittedBy: e.harvested_by,
      text: e.notes ?? "",
      productName: e.product_name,
    }));
    return [...noteItems, ...entryItems].sort((a, b) => (a.date === b.date ? 0 : a.date > b.date ? -1 : 1));
  }, [notes.data, entryNotes.data]);

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
        <QueryBoundary
          loading={notes.isLoading || entryNotes.isLoading}
          error={notes.error ?? entryNotes.error}
          onRetry={() => {
            void notes.refetch();
            void entryNotes.refetch();
          }}
        >
          {feed.length === 0 ? (
            <EmptyState label="No notes yet" compact />
          ) : (
            <Stack gap="xs">
              {feed.map((item) => (
                <Paper
                  key={item.kind === "note" ? `note-${item.id}` : `entry-${item.entry.id}`}
                  withBorder
                  radius="md"
                  p="sm"
                  bg="var(--gp-surface)"
                >
                  <Group justify="space-between" align="flex-start" wrap="nowrap">
                    <div style={{ minWidth: 0 }}>
                      <Group gap={6} mb={4}>
                        <Text size="xs" c="dimmed">
                          {fmtDateOnly(item.date)}
                        </Text>
                        {item.kind === "note" ? (
                          item.lotCode ? (
                            <Badge size="xs" variant="light" color="gpGreen">
                              {item.lotCode}
                            </Badge>
                          ) : (
                            <Badge size="xs" variant="light" color="gray">
                              General
                            </Badge>
                          )
                        ) : (
                          <>
                            {item.lotCode && (
                              <Badge size="xs" variant="light" color="gpGreen">
                                {item.lotCode}
                              </Badge>
                            )}
                            <Badge size="xs" variant="outline" color="gray">
                              {item.productName}
                            </Badge>
                          </>
                        )}
                        <Text size="xs" c="dimmed">
                          · {item.submittedBy}
                        </Text>
                      </Group>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                        {item.text}
                      </Text>
                    </div>
                    {item.kind === "note" ? (
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="red"
                        onClick={() =>
                          del.mutate(item.id, {
                            onSuccess: () => notifySuccess("Deleted."),
                            onError: (e) => notifyError(e),
                          })
                        }
                        aria-label="Delete note"
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    ) : (
                      <Tooltip label="Edit the harvest entry this note is on">
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          onClick={() => setEditingEntry(item.entry)}
                          aria-label="Edit entry"
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                </Paper>
              ))}
            </Stack>
          )}
        </QueryBoundary>
      </SectionCard>

      <EditEntryModal entry={editingEntry} onClose={() => setEditingEntry(null)} />
    </PageLayout>
  );
}
