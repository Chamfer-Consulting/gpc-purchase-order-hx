import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
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

function ManualLinkPanel({ initialPoId }: { initialPoId?: number }) {
  const [poId, setPoId] = useState<number | "">(initialPoId ?? "");
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);
  const link = useManualLink();

  return (
    <Paper withBorder radius="md" p="md">
      <Title order={4} mb="sm">
        Manual link
      </Title>
      <Group align="flex-end" mb="sm">
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
        <Table fz="sm">
          <Table.Tbody>
            {hits.data.map((h) => (
              <Table.Tr key={h.invoice_id}>
                <Table.Td>{h.doc_number ?? h.invoice_id}</Table.Td>
                <Table.Td>{h.customer_name}</Table.Td>
                <Table.Td>{h.txn_date}</Table.Td>
                <Table.Td>{h.total_amt != null ? fmtCurrency(h.total_amt) : "—"}</Table.Td>
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
      )}
      {link.error && (
        <Text size="xs" c="red">
          {(link.error as Error).message}
        </Text>
      )}
      {link.isSuccess && (
        <Text size="xs" c="teal">
          Linked.
        </Text>
      )}
    </Paper>
  );
}

function Lines({ items }: { items: LineItem[] }) {
  if (!items?.length) return <Text size="xs" c="dimmed">no line items</Text>;
  return (
    <Table withRowBorders={false} verticalSpacing={2} fz="xs">
      <Table.Tbody>
        {items.map((it, i) => (
          <Table.Tr key={i}>
            <Table.Td>{it.product_name ?? "?"}{it.container_size ? ` ${it.container_size}` : ""}</Table.Td>
            <Table.Td ta="right" style={{ fontVariantNumeric: "tabular-nums" }}>{it.quantity ?? "?"}</Table.Td>
            <Table.Td ta="right" style={{ fontVariantNumeric: "tabular-nums" }}>{fmtCurrency(it.line_total ?? null, true)}</Table.Td>
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
      <SimpleGrid cols={2} spacing="md">
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
        <Button size="xs" variant="default" color="red" onClick={() => reject.mutate(ref)} loading={reject.isPending}>
          Not a match
        </Button>
      </Group>
    </Card>
  );
}

export function MatchPage() {
  const { data, isLoading, error } = useMatchReview();
  const run = useRunMatching();

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Match &amp; Reconcile</Title>
        <Button size="xs" onClick={() => run.mutate()} loading={run.isPending}>
          Run matching
        </Button>
      </Group>
      {run.data && (
        <Text size="sm" c="dimmed">
          {Object.entries(run.data)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </Text>
      )}

      {error && (
        <Alert color="red" title="Couldn't load">
          {(error as Error).message}
        </Alert>
      )}
      {isLoading && <Loader />}

      {data && (
        <>
          <Text size="sm" c="dimmed">
            {data.candidates.length} candidate link(s) awaiting a decision · {data.unlinked.length} PO(s) with no
            match
          </Text>

          <ManualLinkPanel />

          {data.unlinked.length > 0 && (
            <Paper withBorder radius="md" p="md">
              <Title order={4} mb="sm">
                Unlinked POs
              </Title>
              <Group gap="xs">
                {data.unlinked.map((u) => (
                  <Anchor key={u.po_id} component={Link} to={`/po/${u.po_id}`} size="sm">
                    {u.po_number ?? u.po_id}
                    {u.customer_name ? ` · ${u.customer_name}` : ""}
                  </Anchor>
                ))}
              </Group>
            </Paper>
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
              <Text size="sm" c="dimmed">
                Nothing to review. Run matching after a QuickBooks sync to surface new candidates.
              </Text>
            )}
          </Stack>
        </>
      )}
    </Stack>
  );
}
