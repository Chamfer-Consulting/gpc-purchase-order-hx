import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  NumberInput,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  PO_STATUSES,
  useInvoiceSearch,
  useLinkInvoice,
  usePo,
  useRegroup,
  useSavePo,
  useSetStatus,
  useSoftDelete,
  useUnlinkInvoice,
  useVoidLine,
  type AuditEntry,
  type PoHeader,
  type PoLineItem,
  type PoLink,
  type PoRevision,
  type PoStatus,
} from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";

const EMPTY: PoLineItem = {
  product_raw: "",
  product_name: "",
  container_size: "",
  quantity: null,
  unit_price: null,
  line_total: null,
  additional_cost: null,
};

const STATUS_COLOR: Record<PoStatus, string> = {
  active: "teal",
  draft: "gray",
  cancelled: "orange",
  withdrawn: "orange",
  voided: "red",
  deleted: "red",
};

export function EditPoPage() {
  const { id } = useParams();
  const poId = Number(id);
  const { data, isLoading, error } = usePo(poId);
  const save = useSavePo(poId);
  const setStatus = useSetStatus(poId);
  const softDelete = useSoftDelete(poId);
  const voidLine = useVoidLine(poId);

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  // Each row carries a stable client key (_rk) so React doesn't reattach an input's
  // state to the wrong line when a middle row is deleted.
  const [items, setItems] = useState<(PoLineItem & { _rk: string })[]>([]);
  const rk = useRef(0);
  const nextRk = () => `r${rk.current++}`;

  const [statusDraft, setStatusDraft] = useState<PoStatus>("active");
  const [statusReason, setStatusReason] = useState("");
  const [pendingReactivate, setPendingReactivate] = useState(false);

  useEffect(() => {
    if (data) {
      setHeader(data.header);
      setItems(data.items.map((it) => ({ ...it, _rk: nextRk() })));
      setStatusDraft(data.header.status ?? "active");
      setStatusReason(data.header.status_reason ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (isLoading) return <Loader />;
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;
  if (!data) return null;

  const status = data.header.status ?? "active";
  // Moving a non-active PO back to 'active' is the one status change gated by a
  // warning block — it re-enters every report and revenue total.
  const reactivating = status !== "active" && statusDraft === "active";
  const applyStatus = () =>
    setStatus.mutate({ status: statusDraft, reason: statusReason || null });
  const set = (k: keyof PoHeader, v: unknown) => setHeader((h) => ({ ...h, [k]: v }));
  const setItem = (i: number, k: keyof PoLineItem, v: unknown) =>
    setItems((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <Stack gap="lg" maw={960}>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>Edit PO {data.header.po_number ?? poId}</Title>
          <Badge color={STATUS_COLOR[status]} variant={status === "active" ? "light" : "filled"}>
            {status}
          </Badge>
          {data.header.edited && <Badge variant="light">edited — protected from sync</Badge>}
        </Group>
        <Anchor component={Link} to="/po/new" size="sm">
          + New PO
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed">
        {data.header.source_file}
        {data.header.status_at ? ` · status set ${data.header.status_at.slice(0, 16).replace("T", " ")}` : ""}
      </Text>

      {status !== "active" && (
        <Alert color={STATUS_COLOR[status]} variant="light">
          This order is <b>{status}</b>
          {data.header.status_reason ? ` — ${data.header.status_reason}` : ""}. It is hidden from
          reports and skipped by the extraction pipeline.
        </Alert>
      )}

      {/* ---------- header fields ---------- */}
      <Group grow>
        <TextInput label="PO number" value={header.po_number ?? ""} onChange={(e) => set("po_number", e.currentTarget.value)} />
        <TextInput label="Customer" value={header.customer_name ?? ""} onChange={(e) => set("customer_name", e.currentTarget.value)} />
      </Group>
      <Group grow>
        <TextInput label="PO date" placeholder="YYYY-MM-DD" value={header.po_date ?? ""} onChange={(e) => set("po_date", e.currentTarget.value)} />
        <TextInput label="Delivery date" placeholder="YYYY-MM-DD" value={header.delivery_date ?? ""} onChange={(e) => set("delivery_date", e.currentTarget.value)} />
      </Group>
      <Group grow>
        <NumberInput label="Subtotal" value={header.subtotal ?? undefined} onChange={(v) => set("subtotal", v === "" ? null : Number(v))} decimalScale={2} />
        <NumberInput label="Tax" value={header.tax ?? undefined} onChange={(v) => set("tax", v === "" ? null : Number(v))} decimalScale={2} />
        <NumberInput label="Total" value={header.total ?? undefined} onChange={(v) => set("total", v === "" ? null : Number(v))} decimalScale={2} />
      </Group>

      {/* ---------- line items ---------- */}
      <div style={{ overflowX: "auto" }}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Product</Table.Th>
              <Table.Th>Size</Table.Th>
              <Table.Th>Qty</Table.Th>
              <Table.Th>Unit price</Table.Th>
              <Table.Th>Adtl. cost</Table.Th>
              <Table.Th>Line total</Table.Th>
              <Table.Th>Void</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((it, i) => {
              const voided = !!it.voided;
              const cell = { style: voided ? { opacity: 0.45, textDecoration: "line-through" } : undefined };
              return (
                <Table.Tr key={it._rk}>
                  <Table.Td {...cell}>
                    <TextInput size="xs" value={it.product_name ?? it.product_raw ?? ""} onChange={(e) => setItem(i, "product_name", e.currentTarget.value)} />
                  </Table.Td>
                  <Table.Td w={80} {...cell}>
                    <TextInput size="xs" value={it.container_size ?? ""} onChange={(e) => setItem(i, "container_size", e.currentTarget.value)} />
                  </Table.Td>
                  <Table.Td w={90} {...cell}>
                    <NumberInput size="xs" hideControls value={it.quantity ?? undefined} onChange={(v) => setItem(i, "quantity", v === "" ? null : Number(v))} />
                  </Table.Td>
                  <Table.Td w={110} {...cell}>
                    <NumberInput size="xs" hideControls decimalScale={2} value={it.unit_price ?? undefined} onChange={(v) => setItem(i, "unit_price", v === "" ? null : Number(v))} />
                  </Table.Td>
                  <Table.Td w={110} {...cell}>
                    <NumberInput size="xs" hideControls decimalScale={2} value={it.additional_cost ?? undefined} onChange={(v) => setItem(i, "additional_cost", v === "" ? null : Number(v))} />
                  </Table.Td>
                  <Table.Td w={110} {...cell}>
                    <NumberInput size="xs" hideControls decimalScale={2} value={it.line_total ?? undefined} onChange={(v) => setItem(i, "line_total", v === "" ? null : Number(v))} />
                  </Table.Td>
                  <Table.Td w={60}>
                    {it.id ? (
                      <Tooltip label={voided ? "Un-void this line" : "Void this line (kept, excluded from totals & reports)"}>
                        <ActionIcon
                          variant={voided ? "filled" : "subtle"}
                          color={voided ? "red" : "gray"}
                          loading={voidLine.isPending}
                          onClick={() =>
                            voidLine.mutate({
                              line_id: it.id as number,
                              voided: !voided,
                              reason: voided ? null : window.prompt("Void reason (optional)") ?? null,
                            })
                          }
                        >
                          ∅
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                  </Table.Td>
                  <Table.Td w={40}>
                    <ActionIcon variant="subtle" color="red" onClick={() => setItems((r) => r.filter((_, j) => j !== i))}>
                      ×
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </div>
      <Button size="xs" variant="default" w="fit-content" onClick={() => setItems((r) => [...r, { ...EMPTY, _rk: nextRk() }])}>
        Add line
      </Button>

      <Textarea label="Notes" value={header.notes ?? ""} onChange={(e) => set("notes", e.currentTarget.value)} autosize minRows={2} />

      <Group>
        <Button
          onClick={() =>
            // _rk is a client-only key; the backend's LineItemIn ignores extra fields.
            save.mutate({ header, items, removed_items: data.removed_items })
          }
          loading={save.isPending}
        >
          Save edit
        </Button>
        {save.data && (
          <Text size="sm" c={save.data.math_check_failed ? "red" : "green"}>
            {save.data.math_check_failed
              ? `Saved — math check: ${save.data.math_check_detail}`
              : "Saved. Math checks out."}
          </Text>
        )}
        {save.error && (
          <Text size="sm" c="red">
            {(save.error as Error).message}
          </Text>
        )}
      </Group>

      <Divider my="xs" />

      {/* ---------- lifecycle status ---------- */}
      <Paper withBorder p="md" radius="md">
        <Title order={4} mb="sm">
          Lifecycle
        </Title>
        <Group align="flex-end">
          <Select
            label="Status"
            data={PO_STATUSES.map((s) => ({ value: s, label: s }))}
            value={statusDraft}
            onChange={(v) => v && setStatusDraft(v as PoStatus)}
            w={160}
          />
          <TextInput
            label="Reason"
            placeholder="why (kept on the audit trail)"
            value={statusReason}
            onChange={(e) => setStatusReason(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button
            variant="light"
            loading={setStatus.isPending}
            disabled={statusDraft === status && statusReason === (data.header.status_reason ?? "")}
            onClick={() => (reactivating ? setPendingReactivate(true) : applyStatus())}
          >
            Apply
          </Button>
        </Group>

        <Group mt="sm">
          {status === "active" ? (
            <Button
              color="red"
              variant="light"
              loading={softDelete.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "Soft-delete this PO? It stays in the database but is hidden everywhere and can be restored.",
                  )
                )
                  softDelete.mutate({ reason: window.prompt("Delete reason (optional)") ?? null });
              }}
            >
              Delete PO
            </Button>
          ) : (
            <Button
              color="orange"
              variant="light"
              onClick={() => {
                setStatusDraft("active");
                setPendingReactivate(true);
              }}
            >
              Reactivate order…
            </Button>
          )}
        </Group>

        {pendingReactivate && (
          <Alert
            mt="md"
            color="orange"
            variant="light"
            title={`Reactivate PO ${data.header.po_number ?? poId}?`}
          >
            <Text size="sm">
              This order is currently <b>{status}</b>. Bringing it back to <b>active</b> will:
            </Text>
            <ul style={{ margin: "6px 0 6px 18px", padding: 0 }}>
              <li>return it to every report, chart and analytics total — its revenue counts again</li>
              <li>put it back in the extraction review queue if it still has unresolved issues</li>
              <li>make it visible to invoice matching again</li>
            </ul>
            <Text size="sm">
              It stays marked <b>edited</b>, so the extraction pipeline still won&apos;t overwrite it.
              The change is recorded on the audit trail
              {statusReason ? <> with the reason “{statusReason}”</> : " (add a reason above if you want one)"}.
            </Text>
            <Group mt="sm">
              <Button
                color="orange"
                loading={setStatus.isPending}
                onClick={() =>
                  setStatus.mutate(
                    { status: "active", reason: statusReason || null },
                    { onSuccess: () => setPendingReactivate(false) },
                  )
                }
              >
                Reactivate order
              </Button>
              <Button variant="subtle" onClick={() => setPendingReactivate(false)}>
                Keep it {status}
              </Button>
            </Group>
          </Alert>
        )}
      </Paper>

      <RevisionsPanel poId={poId} revisions={data.revisions ?? []} />
      <LinksPanel poId={poId} links={data.links ?? []} />
      <AuditPanel entries={data.audit ?? []} />
    </Stack>
  );
}

/* -------------------------------------------------------------------------- */

function RevisionsPanel({ poId, revisions }: { poId: number; revisions: PoRevision[] }) {
  const regroup = useRegroup(poId);
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="sm">
        <Title order={4}>Revision chain</Title>
        <Button
          size="xs"
          variant="subtle"
          loading={regroup.isPending}
          onClick={() => regroup.mutate({ standalone: true })}
        >
          Mark this PO standalone
        </Button>
      </Group>
      {revisions.length === 0 ? (
        <Text size="sm" c="dimmed">
          No sibling orders (same customer + delivery date, or same PO number).
        </Text>
      ) : (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>PO</Table.Th>
              <Table.Th>Customer</Table.Th>
              <Table.Th>PO date</Table.Th>
              <Table.Th>Delivery</Table.Th>
              <Table.Th>Total</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {revisions.map((r) => (
              <Table.Tr key={r.po_id}>
                <Table.Td>
                  <Anchor component={Link} to={`/po/${r.po_id}`}>
                    {r.po_number ?? r.po_id}
                  </Anchor>{" "}
                  {r.is_revision && <Badge size="xs" variant="light">rev</Badge>}
                  {r.status !== "active" && (
                    <Badge size="xs" color={STATUS_COLOR[r.status]} ml={4}>
                      {r.status}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>{r.customer_name}</Table.Td>
                <Table.Td>{r.po_date}</Table.Td>
                <Table.Td>{r.delivery_date}</Table.Td>
                <Table.Td>{r.total != null ? fmtCurrency(r.total) : "—"}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="subtle"
                    loading={regroup.isPending}
                    onClick={() =>
                      regroup.mutate({ revision_of: r.po_number ?? r.source_file })
                    }
                  >
                    This is a revision of {r.po_number ?? "it"}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {regroup.isSuccess && (
        <Text size="xs" c="dimmed" mt="xs">
          Saved. Grouping is applied on the next extraction run.
        </Text>
      )}
      {regroup.error && (
        <Text size="xs" c="red" mt="xs">
          {(regroup.error as Error).message}
        </Text>
      )}
    </Paper>
  );
}

/* -------------------------------------------------------------------------- */

function LinksPanel({ poId, links }: { poId: number; links: PoLink[] }) {
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);
  const link = useLinkInvoice(poId);
  const unlink = useUnlinkInvoice(poId);

  return (
    <Paper withBorder p="md" radius="md">
      <Title order={4} mb="sm">
        Invoice links
      </Title>
      {links.length === 0 ? (
        <Text size="sm" c="dimmed">
          No invoice linked to this PO yet.
        </Text>
      ) : (
        <Table mb="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Invoice</Table.Th>
              <Table.Th>Date</Table.Th>
              <Table.Th>Amount</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {links.map((l) => (
              <Table.Tr key={l.invoice_id}>
                <Table.Td>{l.doc_number ?? l.invoice_id}</Table.Td>
                <Table.Td>{l.txn_date}</Table.Td>
                <Table.Td>{l.total_amt != null ? fmtCurrency(l.total_amt) : "—"}</Table.Td>
                <Table.Td>
                  <Badge
                    size="xs"
                    color={l.confirmed ? "teal" : l.rejected ? "gray" : "yellow"}
                    variant="light"
                  >
                    {l.confirmed ? l.match_method : l.rejected ? "rejected" : "pending"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="subtle"
                    color="red"
                    loading={unlink.isPending}
                    onClick={() => unlink.mutate(l.invoice_id)}
                  >
                    Unlink
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <TextInput
        label="Link another invoice"
        placeholder="invoice number or customer"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      {hits.data && hits.data.length > 0 && (
        <Table mt="xs">
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
                      already linked
                    </Badge>
                  )}
                  <Button
                    size="xs"
                    variant="light"
                    loading={link.isPending}
                    onClick={() => link.mutate({ invoice_id: h.invoice_id })}
                  >
                    Link
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {link.error && (
        <Text size="xs" c="red" mt="xs">
          {(link.error as Error).message}
        </Text>
      )}
    </Paper>
  );
}

/* -------------------------------------------------------------------------- */

function AuditPanel({ entries }: { entries: AuditEntry[] }) {
  const [open, setOpen] = useState(false);
  const summary = useMemo(
    () =>
      entries.map((e) => ({
        ...e,
        delta: JSON.stringify(e.after ?? e.before ?? {}),
      })),
    [entries],
  );

  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between">
        <Title order={4}>Audit trail ({entries.length})</Title>
        <Button size="xs" variant="subtle" onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Show"}
        </Button>
      </Group>
      <Collapse in={open}>
        {entries.length === 0 ? (
          <Text size="sm" c="dimmed" mt="sm">
            No recorded changes.
          </Text>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <Table mt="sm" fz="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Who</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>Change</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {summary.map((e) => (
                  <Table.Tr key={e.id}>
                    <Table.Td>{e.at?.slice(0, 16).replace("T", " ")}</Table.Td>
                    <Table.Td>{e.actor ?? "—"}</Table.Td>
                    <Table.Td>
                      <Badge size="xs" variant="light">
                        {e.action}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <code>{e.delta}</code>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        )}
      </Collapse>
    </Paper>
  );
}
