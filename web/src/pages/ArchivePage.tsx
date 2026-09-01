import { useState } from "react";
import { Link } from "react-router-dom";
import { Anchor, Badge, Table, Tabs } from "@mantine/core";
import { STATUS_COLOR, useArchive, type ArchivedPo } from "@/api/poEdit";
import { PageLayout } from "@/components/PageLayout";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { pageMeta } from "@/nav";

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
  if (rows.length === 0) return <EmptyState label="Nothing in this bucket" compact />;
  return (
    <Table.ScrollContainer minWidth={860} type="native">
      <Table highlightOnHover verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>PO</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Customer</Table.Th>
            <Table.Th>PO date</Table.Th>
            <Table.Th ta="right">Lines</Table.Th>
            <Table.Th ta="right">Total</Table.Th>
            <Table.Th>Reason</Table.Th>
            <Table.Th>Changed</Table.Th>
            <Table.Th>By</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.po_id}>
              <Table.Td>
                <Anchor component={Link} to={`/po/${r.po_id}`} size="sm">
                  {r.po_number ?? r.po_id}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <StatusTag status={r.status} />
              </Table.Td>
              <Table.Td>{r.customer_name ?? "—"}</Table.Td>
              <Table.Td>{r.po_date ?? "—"}</Table.Td>
              <Table.Td ta="right" style={NUMERIC_STYLE}>
                {r.n_items}
              </Table.Td>
              <Table.Td ta="right" style={NUMERIC_STYLE}>
                {r.total != null ? fmtCurrency(r.total) : "—"}
              </Table.Td>
              <Table.Td>{r.status_reason ?? "—"}</Table.Td>
              <Table.Td>{(r.status_at ?? r.deleted_at)?.slice(0, 16).replace("T", " ") ?? "—"}</Table.Td>
              <Table.Td>{r.edited_by ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function ArchivePage() {
  const [tab, setTab] = useState<string>("all");
  const { data, isLoading, error, refetch } = useArchive(tab === "all" ? undefined : tab);
  const counts = data?.counts ?? {};
  const meta = pageMeta("/archive")!;

  const shown = data?.rows.length ?? 0;
  const total = counts[tab];
  const subtitle =
    isLoading || shown === 0
      ? undefined
      : total != null && total > shown
        ? `${shown} of ${total} shown`
        : `${shown} shown`;

  return (
    <PageLayout title={meta.title} description={meta.description} breadcrumbs={meta.breadcrumbs}>
      <SectionCard title="Archived orders" subtitle={subtitle}>
        <Tabs value={tab} onChange={(v) => v && setTab(v)} keepMounted={false}>
          <Tabs.List>
            {BUCKETS.map((b) => (
              <Tabs.Tab
                key={b.value}
                value={b.value}
                rightSection={
                  counts[b.value] != null ? (
                    <Badge
                      size="xs"
                      variant="light"
                      color={b.value === "all" ? "gray" : STATUS_COLOR[b.value as ArchivedPo["status"]]}
                    >
                      {counts[b.value]}
                    </Badge>
                  ) : null
                }
              >
                {b.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>

          <Tabs.Panel value={tab} pt="md">
            <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
              <ArchiveTable rows={data?.rows ?? []} />
            </QueryBoundary>
          </Tabs.Panel>
        </Tabs>
      </SectionCard>
    </PageLayout>
  );
}
