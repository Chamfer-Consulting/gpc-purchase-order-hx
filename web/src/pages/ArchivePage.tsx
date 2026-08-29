import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Anchor,
  Badge,
  Group,
  Loader,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { STATUS_COLOR, useArchive, type ArchivedPo } from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";

// Tabs, in order. "all" first; the rest are the non-active buckets.
const BUCKETS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "cancelled", label: "Cancelled" },
  { value: "withdrawn", label: "Withdrawn" },
  { value: "voided", label: "Voided" },
  { value: "deleted", label: "Deleted" },
  { value: "draft", label: "Draft" },
];

function StatusTag({ status }: { status: ArchivedPo["status"] }) {
  return (
    <Badge color={STATUS_COLOR[status]} variant="filled" size="sm">
      {status}
    </Badge>
  );
}

function ArchiveTable({ rows }: { rows: ArchivedPo[] }) {
  if (rows.length === 0)
    return (
      <Text size="sm" c="dimmed" mt="md">
        Nothing here.
      </Text>
    );
  return (
    <div style={{ overflowX: "auto" }}>
      <Table mt="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>PO</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Customer</Table.Th>
            <Table.Th>PO date</Table.Th>
            <Table.Th>Lines</Table.Th>
            <Table.Th>Total</Table.Th>
            <Table.Th>Reason</Table.Th>
            <Table.Th>Changed</Table.Th>
            <Table.Th>By</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.po_id}>
              <Table.Td>
                <Anchor component={Link} to={`/po/${r.po_id}`}>
                  {r.po_number ?? r.po_id}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <StatusTag status={r.status} />
              </Table.Td>
              <Table.Td>{r.customer_name ?? "—"}</Table.Td>
              <Table.Td>{r.po_date ?? "—"}</Table.Td>
              <Table.Td style={{ fontVariantNumeric: "tabular-nums" }}>{r.n_items}</Table.Td>
              <Table.Td style={{ fontVariantNumeric: "tabular-nums" }}>
                {r.total != null ? fmtCurrency(r.total) : "—"}
              </Table.Td>
              <Table.Td>{r.status_reason ?? "—"}</Table.Td>
              <Table.Td>
                {(r.status_at ?? r.deleted_at)?.slice(0, 16).replace("T", " ") ?? "—"}
              </Table.Td>
              <Table.Td>{r.edited_by ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </div>
  );
}

export function ArchivePage() {
  const [tab, setTab] = useState<string>("all");
  const { data, isLoading, error } = useArchive(tab === "all" ? undefined : tab);
  const counts = data?.counts ?? {};

  return (
    <Stack gap="md">
      <Title order={2}>Archive</Title>
      <Text size="sm" c="dimmed">
        Purchase orders that aren&apos;t active — cancelled, withdrawn, voided, soft-deleted, or
        still a draft. Each is hidden from every report; open one to see its history or reactivate
        it.
      </Text>

      {error && (
        <Alert color="red" title="Couldn't load">
          {(error as Error).message}
        </Alert>
      )}

      <Tabs value={tab} onChange={(v) => v && setTab(v)}>
        <Tabs.List>
          {BUCKETS.map((b) => (
            <Tabs.Tab
              key={b.value}
              value={b.value}
              rightSection={
                counts[b.value] != null ? (
                  <Badge size="xs" variant="light" color={b.value === "all" ? "gray" : STATUS_COLOR[b.value as ArchivedPo["status"]]}>
                    {counts[b.value]}
                  </Badge>
                ) : null
              }
            >
              {b.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>

        {BUCKETS.map((b) => (
          <Tabs.Panel key={b.value} value={b.value}>
            {isLoading ? <Loader mt="md" /> : <ArchiveTable rows={data?.rows ?? []} />}
          </Tabs.Panel>
        ))}
      </Tabs>

      {!isLoading && (data?.rows.length ?? 0) > 0 && (
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {data?.rows.length} shown
          </Text>
        </Group>
      )}
    </Stack>
  );
}
