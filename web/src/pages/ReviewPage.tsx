import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Radio,
  Stack,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import {
  useDecisions,
  useDeleteDecision,
  useRevisionCandidates,
  useReviewQueue,
  useUpsertDecision,
  type QueueItem,
} from "@/api/review";
import { DataGrid } from "@/components/DataGrid";
import { useRealtimeInvalidate } from "@/lib/realtime";

function QueueCard({ item }: { item: QueueItem }) {
  const upsert = useUpsertDecision();
  const [verdict, setVerdict] = useState<"is_po" | "not_po" | "revision">("is_po");
  const [revisionOf, setRevisionOf] = useState("");
  const [note, setNote] = useState("");

  function save() {
    upsert.mutate({
      target_kind: item.target_kind,
      target_key: item.target_key,
      verdict: verdict === "revision" ? "is_po" : verdict,
      revision_of: verdict === "revision" ? revisionOf.trim() || null : null,
      note: note.trim() || null,
    });
  }

  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" mb={4}>
        <Text fw={600}>{item.subject ?? item.target_key}</Text>
        <Group gap={6}>
          {item.stale && <Badge color="orange" variant="light">stale</Badge>}
          <Badge color="yellow" variant="light">
            {item.reason}
          </Badge>
        </Group>
      </Group>
      <Text size="xs" c="dimmed">
        {item.from_addrs ?? "—"} · {item.target_kind}:{item.target_key} · {item.n_items} line item(s)
        {item.gmail_url && (
          <>
            {" · "}
            <Anchor href={item.gmail_url} target="_blank" rel="noreferrer">
              open in Gmail ↗
            </Anchor>
          </>
        )}
      </Text>

      {item.snapshot && (
        <Textarea value={item.snapshot} readOnly autosize minRows={3} maxRows={8} mt="xs" styles={{ input: { fontSize: 12 } }} />
      )}

      <Radio.Group value={verdict} onChange={(v) => setVerdict(v as typeof verdict)} mt="sm">
        <Group>
          <Radio value="is_po" label="Purchase order" />
          <Radio value="not_po" label="Not a purchase order" />
          <Radio value="revision" label="Revision of another PO" />
        </Group>
      </Radio.Group>
      {verdict === "revision" && (
        <TextInput
          mt="xs"
          size="xs"
          placeholder="PO number (or gmail-thread:<id> / source_file) this revises"
          value={revisionOf}
          onChange={(e) => setRevisionOf(e.currentTarget.value)}
          description="Next importer run re-extracts this thread as the complete revised order and groups it there."
        />
      )}
      <TextInput mt="xs" size="xs" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
      <Button mt="sm" size="xs" onClick={save} loading={upsert.isPending}>
        Save decision
      </Button>
    </Card>
  );
}

function QueueTab() {
  const { data, isLoading, error } = useReviewQueue();
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;
  if (isLoading) return <Loader />;
  const items = data?.items ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {items.length} extraction(s) flagged, ranked by how suspect they are.
      </Text>
      {items.length === 0 && (
        <Text size="sm" c="dimmed">
          Nothing flagged. New low-confidence extractions appear here.
        </Text>
      )}
      {items.map((it) => (
        <QueueCard key={`${it.target_kind}:${it.target_key}`} item={it} />
      ))}
    </Stack>
  );
}

function CandidatesTab() {
  const { data, isLoading, error } = useRevisionCandidates();
  const upsert = useUpsertDecision();
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;
  if (isLoading) return <Loader />;
  const items = data?.items ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Same customer, same delivery date, different PO numbers — usually a revised PO.
      </Text>
      {items.length === 0 && <Text size="sm" c="dimmed">No candidate pairs.</Text>}
      {items.map((c) => (
        <Card key={`${c.a_po_id}-${c.b_po_id}`} withBorder radius="md" p="sm">
          <Group justify="space-between">
            <Text size="sm">
              <b>{c.customer_name}</b> · delivery {c.delivery_date} · A PO {c.a_po_number ?? "—"} → B PO{" "}
              {c.b_po_number ?? "—"}
            </Text>
            <Button
              size="xs"
              onClick={() =>
                upsert.mutate({
                  target_kind: c.b_kind,
                  target_key: c.b_key,
                  verdict: "is_po",
                  revision_of: c.a_group_key,
                  note: `linked as revision of PO ${c.a_po_number} (delivery ${c.delivery_date})`,
                })
              }
              loading={upsert.isPending}
            >
              B revises A
            </Button>
          </Group>
        </Card>
      ))}
    </Stack>
  );
}

function DecisionsTab() {
  const { data, isLoading, error } = useDecisions();
  const del = useDeleteDecision();
  const [pick, setPick] = useState("");
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;
  if (isLoading) return <Loader />;
  const rows = data?.items ?? [];
  return (
    <Stack>
      <DataGrid
        rows={rows as unknown as Record<string, unknown>[]}
        columns={[
          { key: "target_kind", label: "Kind" },
          { key: "target_key", label: "Target" },
          { key: "verdict", label: "Verdict" },
          { key: "revision_of", label: "Revision of" },
          { key: "note", label: "Note" },
          { key: "reviewer", label: "By" },
          { key: "updated_at", label: "Updated", kind: "date" },
        ]}
        exportName="review_decisions"
      />
      {rows.length > 0 && (
        <Group>
          <TextInput
            size="xs"
            placeholder="kind:key to remove"
            value={pick}
            onChange={(e) => setPick(e.currentTarget.value)}
          />
          <Button
            size="xs"
            color="red"
            variant="light"
            onClick={() => {
              const [k, ...rest] = pick.split(":");
              if (k && rest.length) del.mutate({ target_kind: k, target_key: rest.join(":") });
            }}
          >
            Remove decision
          </Button>
        </Group>
      )}
    </Stack>
  );
}

export function ReviewPage() {
  // Live-update the queue as the pipeline writes new flags / decisions land.
  useRealtimeInvalidate("purchase_orders", ["review-queue", "data-quality"]);
  useRealtimeInvalidate("extraction_reviews", ["review-decisions", "review-queue", "review-candidates"]);

  return (
    <Stack gap="md">
      <Title order={2}>Extraction Review</Title>
      <Text size="sm" c="dimmed" maw={620}>
        Teach the importer what is and isn't a purchase order, and what's a revision of what. Every
        decision is enforced on the next run, fed back as a few-shot example, and gates CI.
      </Text>
      <Tabs defaultValue="queue">
        <Tabs.List>
          <Tabs.Tab value="queue">Queue</Tabs.Tab>
          <Tabs.Tab value="candidates">Possible revisions</Tabs.Tab>
          <Tabs.Tab value="decisions">All decisions</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="queue" pt="md">
          <QueueTab />
        </Tabs.Panel>
        <Tabs.Panel value="candidates" pt="md">
          <CandidatesTab />
        </Tabs.Panel>
        <Tabs.Panel value="decisions" pt="md">
          <DecisionsTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
