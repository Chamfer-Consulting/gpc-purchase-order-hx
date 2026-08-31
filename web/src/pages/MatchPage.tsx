import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  NumberInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import {
  useConfirmLink,
  useManualLink,
  useMatchReview,
  useRejectLink,
  useRunMatching,
  type LineItem,
  type MatchCandidate,
} from "@/api/matching";
import { useInvoiceSearch } from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";
import { PageLayout } from "@/components/PageLayout";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { pageMeta } from "@/nav";

function ManualLinkPanel({ initialPoId }: { initialPoId?: number }) {
  const [poId, setPoId] = useState<number | "">(initialPoId ?? "");
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);
  const link = useManualLink();

  return (
    <SectionCard title="Manual link">
      <Group align="flex-end">
        <NumberInput
          label="PO id"
          value={poId}
          onChange={(v) => setPoId(v === "" ? "" : Number(v))}
          hideControls
          w={120}
        />
        <TextInput
          label="Find invoice"
          placeholder="invoice number or customer"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
      </Group>
      {typeof poId === "number" && hits.data && hits.data.length > 0 && (
        <Table.ScrollContainer minWidth={560} type="native">
          <Table fz="sm">
            <Table.Tbody>
              {hits.data.map((h) => (
                <Table.Tr key={h.invoice_id}>
                  <Table.Td>{h.doc_number ?? h.invoice_id}</Table.Td>
                  <Table.Td>{h.customer_name}</Table.Td>
                  <Table.Td>{h.txn_date}</Table.Td>
                  <Table.Td style={NUMERIC_STYLE}>
                    {h.total_amt != null ? fmtCurrency(h.total_amt) : "—"}
                  </Table.Td>
                  <Table.Td>
                    {h.linked && (
                      <Badge size="xs" color="gray" variant="light" mr="xs">
                        linked
                      </Badge>
                    )}
                    <Button
                      size="xs"
                      variant="light"
                      loading={link.isPending}
                      onClick={() => link.mutate({ po_id: poId, invoice_id: h.invoice_id })}
                    >
                      Link to PO {poId}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {link.error && (
        <Text size="xs" c="red">
          {(link.error as Error).message}
        </Text>
      )}
      {link.isSuccess && (
        <Text size="xs" c="gpGreen.7">
          Linked.
        </Text>
      )}
    </SectionCard>
  );
}

function Lines({ items }: { items: LineItem[] }) {
  if (!items?.length)
    return (
      <Text size="xs" c="dimmed">
        no line items
      </Text>
    );
  return (
    <Table withRowBorders={false} verticalSpacing={2} fz="xs">
      <Table.Tbody>
        {items.map((it, i) => (
          <Table.Tr key={i}>
            <Table.Td>
              {it.product_name ?? "?"}
              {it.container_size ? ` ${it.container_size}` : ""}
            </Table.Td>
            <Table.Td ta="right" style={NUMERIC_STYLE}>
              {it.quantity ?? "?"}
            </Table.Td>
            <Table.Td ta="right" style={NUMERIC_STYLE}>
              {fmtCurrency(it.line_total ?? null, true)}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function CandidateCard({
  c,
  poItems,
  invItems,
}: {
  c: MatchCandidate;
  poItems: LineItem[];
  invItems: LineItem[];
}) {
  const confirm = useConfirmLink();
  const reject = useRejectLink();
  const ref = { po_id: c.po_id, invoice_id: c.invoice_id };

  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>PO {c.po_number ?? c.po_id}</Text>
        <Badge variant="light">
          {c.match_method}
          {c.match_score != null ? ` · ${(c.match_score * 100).toFixed(0)}%` : ""}
        </Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
        <div>
          <Text size="xs" c="dimmed" tt="uppercase">
            Purchase order
          </Text>
          <Text size="sm">
            {c.po_customer} · {c.po_date?.slice(0, 10)} · {fmtCurrency(c.po_total)}
          </Text>
          <Lines items={poItems} />
        </div>
        <div>
          <Text size="xs" c="dimmed" tt="uppercase">
            Invoice {c.doc_number}
          </Text>
          <Text size="sm">
            {c.inv_customer} · {c.txn_date?.slice(0, 10)} · {fmtCurrency(c.total_amt)}
          </Text>
          <Lines items={invItems} />
        </div>
      </SimpleGrid>
      <Group mt="sm">
        <Button size="xs" onClick={() => confirm.mutate(ref)} loading={confirm.isPending}>
          Confirm match
        </Button>
        <Button
          size="xs"
          variant="default"
          color="red"
          onClick={() => reject.mutate(ref)}
          loading={reject.isPending}
        >
          Not a match
        </Button>
      </Group>
    </Card>
  );
}

export function MatchPage() {
  const { data, isLoading, error, refetch } = useMatchReview();
  const run = useRunMatching();
  const meta = pageMeta("/match")!;

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      actions={
        <Button
          size="sm"
          leftSection={<IconPlayerPlay size={15} />}
          onClick={() => run.mutate()}
          loading={run.isPending}
        >
          Run matching
        </Button>
      }
    >
      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        {data && (
          <Stack gap="lg">
            {run.data && (
              <Text size="sm" c="dimmed">
                {Object.entries(run.data)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ")}
              </Text>
            )}

            <Text size="sm" c="dimmed">
              {data.candidates.length} candidate link(s) awaiting a decision ·{" "}
              {data.unlinked.length} PO(s) with no match
            </Text>

            <ManualLinkPanel />

            {data.unlinked.length > 0 && (
              <SectionCard title="Unlinked POs">
                <Group gap="xs">
                  {data.unlinked.map((u) => (
                    <Anchor key={u.po_id} component={Link} to={`/po/${u.po_id}`} size="sm">
                      {u.po_number ?? u.po_id}
                      {u.customer_name ? ` · ${u.customer_name}` : ""}
                    </Anchor>
                  ))}
                </Group>
              </SectionCard>
            )}

            <Stack>
              {data.candidates.map((c) => (
                <CandidateCard
                  key={`${c.po_id}-${c.invoice_id}`}
                  c={c}
                  poItems={data.po_items[String(c.po_id)] ?? []}
                  invItems={data.inv_items[String(c.invoice_id)] ?? []}
                />
              ))}
              {data.candidates.length === 0 && (
                <EmptyState
                  title="Nothing to review"
                  description="Run matching after a QuickBooks sync to surface new candidates."
                />
              )}
            </Stack>
          </Stack>
        )}
      </QueryBoundary>
    </PageLayout>
  );
}
