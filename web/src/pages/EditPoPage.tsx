import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import { IconDeviceFloppy, IconPlus } from "@tabler/icons-react";
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
  STATUS_COLOR,
  type AuditEntry,
  type PoHeader,
  type PoLineItem,
  type PoLink,
  type PoRevision,
  type PoSources,
  type PoStatus,
} from "@/api/poEdit";
import {
  openDocument,
  useCaptureDocs,
  useDeleteDoc,
  usePoDocuments,
  useUploadDoc,
  type PoDocument,
} from "@/api/poDocs";
import { fmtCurrency } from "@/lib/format";
import { promptReason } from "@/lib/modals";
import { useMe } from "@/api/me";
import { notifySuccess } from "@/lib/notify";
import { conflictInfo, errorMessage, fieldErrors, isConflict } from "@/lib/errors";
import { useUnsavedGuard } from "@/hooks/useUnsavedGuard";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { PoHeaderFields, headerErrors } from "@/components/po/PoHeaderFields";
import { EMPTY_LINE, PoLineItemsEditor, type EditableLine } from "@/components/po/PoLineItemsEditor";
import { NUMERIC_STYLE } from "@/theme/tokens";

/** Compare the editable slice of the form to the server copy. */
function formEqual(header: Partial<PoHeader>, items: EditableLine[], data: {
  header: PoHeader;
  items: PoLineItem[];
}): boolean {
  const hk: (keyof PoHeader)[] = [
    "po_number", "customer_name", "po_date", "delivery_date", "subtotal", "tax", "total", "notes",
  ];
  for (const k of hk) if ((header[k] ?? null) !== (data.header[k] ?? null)) return false;
  if (items.length !== data.items.length) return false;
  const ik: (keyof PoLineItem)[] = [
    "id", "product_name", "container_size", "quantity", "unit_price", "line_total",
    "additional_cost", "voided",
  ];
  for (let i = 0; i < items.length; i++) {
    for (const k of ik) if ((items[i][k] ?? null) !== (data.items[i][k] ?? null)) return false;
  }
  return true;
}

const DOC_KIND_LABEL: Record<PoDocument["kind"], string> = {
  po_pdf: "PO PDF",
  invoice_pdf: "Invoice PDF",
  email_pdf: "Email PDF",
  other: "File",
};


export function EditPoPage() {
  const { id } = useParams();
  const poId = Number(id);
  const { data, isLoading, error, refetch } = usePo(poId);
  const { canEdit, canAdmin, roleKnown } = useMe();
  const save = useSavePo(poId);
  const setStatus = useSetStatus(poId);
  const softDelete = useSoftDelete(poId);
  const voidLine = useVoidLine(poId);

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  // Each row carries a stable client key (_rk) so React doesn't reattach an input's
  // state to the wrong line when a middle row is deleted.
  const [items, setItems] = useState<EditableLine[]>([]);
  const rk = useRef(0);
  const makeRow = (seed?: Partial<PoLineItem>): EditableLine => ({
    ...EMPTY_LINE,
    ...seed,
    _rk: `r${rk.current++}`,
  });

  const [statusDraft, setStatusDraft] = useState<PoStatus>("active");
  const [statusReason, setStatusReason] = useState("");
  const [pendingReactivate, setPendingReactivate] = useState(false);
  // the lock_version we last seeded the form from — if the server's moves past
  // this while the form is dirty, someone else saved.
  const [seededVersion, setSeededVersion] = useState<number | undefined>(undefined);

  const isDirty = useMemo(
    () => (data ? !formEqual(header, items, data) : false),
    [header, items, data],
  );
  const dirtyRef = useRef(false);
  dirtyRef.current = isDirty;

  function reseed(d: NonNullable<typeof data>) {
    setHeader(d.header);
    setItems(d.items.map((it) => makeRow(it)));
    setStatusDraft(d.header.status ?? "active");
    setStatusReason(d.header.status_reason ?? "");
    setSeededVersion(d.header.lock_version);
  }

  useEffect(() => {
    // Only take the server copy when the form is clean — a background refetch
    // (fired by a void / status / link mutation on this page) must not wipe edits.
    if (data && !dirtyRef.current) reseed(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  useUnsavedGuard(isDirty);
  useHotkeys(
    [
      [
        "mod+S",
        (e) => {
          e.preventDefault();
          if (canEdit && isDirty && data) doSave();
        },
      ],
    ],
    [],
  );

  const crumbs = [{ label: "Reconcile", to: "/reconcile" }, { label: "Purchase order" }];

  if (isLoading) {
    return <PageLayout title="Purchase order" breadcrumbs={crumbs} width="form" loading />;
  }
  if (error || !data) {
    return (
      <PageLayout
        title="Purchase order"
        breadcrumbs={crumbs}
        width="form"
        error={error ?? new Error("Not found")}
        onRetry={() => void refetch()}
      >
        {null}
      </PageLayout>
    );
  }

  const status = data.header.status ?? "active";
  // Moving a non-active PO back to 'active' is the one status change gated by a
  // warning block — it re-enters every report and revenue total.
  const reactivating = status !== "active" && statusDraft === "active";
  const applyStatus = () =>
    setStatus.mutate({
      status: statusDraft,
      reason: statusReason || null,
      expected_version: data.header.lock_version,
    });
  const set = (k: keyof PoHeader, v: unknown) => setHeader((h) => ({ ...h, [k]: v }));

  const errors = { ...headerErrors(header), ...fieldErrors(save.error) };
  const serverMovedAhead =
    isDirty && seededVersion != null && data.header.lock_version !== seededVersion;

  function doSave() {
    save.mutate(
      {
        header,
        items,
        removed_items: data!.removed_items,
        expected_version: seededVersion ?? data!.header.lock_version,
      },
      { onSuccess: () => notifySuccess("Saved.") },
    );
  }

  return (
    <PageLayout
      title={`PO ${data.header.po_number ?? poId}`}
      description={data.header.source_file}
      breadcrumbs={[{ label: "Reconcile", to: "/reconcile" }, { label: `PO ${data.header.po_number ?? poId}` }]}
      width="form"
      actions={
        <Button component={Link} to="/po/new" size="sm" variant="light" leftSection={<IconPlus size={15} />}>
          New PO
        </Button>
      }
    >
      <Stack gap="lg">
        {roleKnown && !canEdit && (
          <Alert color="gray" variant="light" title="View-only access">
            Your account can view purchase orders but not change them. Ask an admin for the editor
            role to save edits, void lines, or link invoices.
          </Alert>
        )}
        <Group gap="xs">
          <Badge color={STATUS_COLOR[status]} variant={status === "active" ? "light" : "filled"}>
            {status}
          </Badge>
          {data.header.edited && <Badge variant="light">edited — protected from sync</Badge>}
          {data.header.status_at && (
            <Text size="xs" c="dimmed">
              status set {data.header.status_at.slice(0, 16).replace("T", " ")}
            </Text>
          )}
        </Group>

        {status !== "active" && (
          <Alert color={STATUS_COLOR[status]} variant="light">
            This order is <b>{status}</b>
            {data.header.status_reason ? ` — ${data.header.status_reason}` : ""}. It is hidden from
            reports and skipped by the extraction pipeline.
          </Alert>
        )}

        {serverMovedAhead && (
          <Alert color="orange" variant="light" title="This order changed on the server">
            Someone else saved a newer version while you were editing. Save to overwrite theirs
            (you'll get a conflict), or discard your changes and reload.
            <Group mt="xs" gap="xs">
              <Button size="xs" variant="light" color="orange" onClick={() => reseed(data)}>
                Discard mine & reload
              </Button>
            </Group>
          </Alert>
        )}

        <SectionCard title="Order details">
          <PoHeaderFields
            value={header}
            onChange={(p) => setHeader((h) => ({ ...h, ...p }))}
            errors={errors}
            disabled={!canEdit}
          />
        </SectionCard>

        <SectionCard title="Line items">
          <PoLineItemsEditor
            items={items}
            onChange={setItems}
            makeRow={makeRow}
            headerTotal={header.total ?? null}
            showVoid
            disabled={!canEdit}
            onVoidLine={(it) => {
              const lineId = it.id as number;
              if (it.voided) {
                voidLine.mutate({
                  line_id: lineId,
                  voided: false,
                  reason: null,
                  expected_version: data.header.lock_version,
                });
              } else {
                promptReason({
                  title: "Void this line",
                  description: "The line is kept but excluded from totals and reports.",
                  label: "Reason (optional)",
                  confirmLabel: "Void line",
                  confirmColor: "red",
                  onSubmit: (reason) =>
                    voidLine.mutate({
                      line_id: lineId,
                      voided: true,
                      reason,
                      expected_version: data.header.lock_version,
                    }),
                });
              }
            }}
          />

          <Textarea
            label="Notes"
            value={header.notes ?? ""}
            onChange={(e) => set("notes", e.currentTarget.value)}
            autosize
            minRows={2}
            disabled={!canEdit}
          />

          {save.data && save.data.math_check_failed && (
            <Alert color="orange" variant="light" title="Math check">
              {save.data.math_check_detail || "Line items or totals don't reconcile."} — saved anyway.
            </Alert>
          )}
          {save.error && isConflict(save.error) ? (
            <Alert color="orange" variant="light" title="This order changed while you were editing">
              {(() => {
                const c = conflictInfo(save.error);
                return (
                  <Text size="sm">
                    {c.editedBy ? `${c.editedBy} saved a newer version` : "A newer version was saved"}
                    {c.editedAt ? ` at ${c.editedAt.slice(0, 16).replace("T", " ")}` : ""}. Reload to
                    pick up their changes, then re-apply yours.
                  </Text>
                );
              })()}
              <Button size="xs" mt="xs" variant="light" color="orange" onClick={() => reseed(data)}>
                Discard mine & reload
              </Button>
            </Alert>
          ) : save.error && Object.keys(fieldErrors(save.error)).length === 0 ? (
            <Text size="sm" c="red">
              {errorMessage(save.error)}
            </Text>
          ) : null}
        </SectionCard>

        {isDirty && canEdit && (
          <Box
            style={{
              position: "sticky",
              bottom: 12,
              zIndex: 4,
              background: "var(--gp-surface)",
              border: "1px solid var(--mantine-color-gpGreen-4)",
              borderRadius: "var(--mantine-radius-md)",
              boxShadow: "var(--mantine-shadow-md)",
              padding: "10px 14px",
            }}
          >
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" fw={600}>
                Unsaved changes
              </Text>
              <Group gap="xs">
                <Button size="xs" variant="default" onClick={() => reseed(data)}>
                  Discard
                </Button>
                <Button
                  size="xs"
                  leftSection={<IconDeviceFloppy size={14} />}
                  loading={save.isPending}
                  onClick={doSave}
                >
                  Save edit
                </Button>
              </Group>
            </Group>
          </Box>
        )}

        <SectionCard title="Lifecycle">
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
              disabled={
                !canAdmin ||
                (statusDraft === status && statusReason === (data.header.status_reason ?? ""))
              }
              onClick={() => (reactivating ? setPendingReactivate(true) : applyStatus())}
            >
              Apply
            </Button>
          </Group>
          {roleKnown && !canAdmin && (
            <Text size="xs" c="dimmed">
              Changing lifecycle status, deleting or restoring an order needs the admin role.
            </Text>
          )}

          <Group mt="sm">
            {status === "active" ? (
              <Button
                color="red"
                variant="light"
                loading={softDelete.isPending}
                disabled={!canAdmin}
                onClick={() =>
                  promptReason({
                    title: "Soft-delete this PO?",
                    description:
                      "It stays in the database but is hidden everywhere and can be restored later.",
                    label: "Delete reason (optional)",
                    confirmLabel: "Delete PO",
                    confirmColor: "red",
                    onSubmit: (reason) => softDelete.mutate({ reason }),
                  })
                }
              >
                Delete PO
              </Button>
            ) : (
              <Button
                color="orange"
                variant="light"
                disabled={!canAdmin}
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
            <Alert mt="md" color="orange" variant="light" title={`Reactivate PO ${data.header.po_number ?? poId}?`}>
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
        </SectionCard>

        <RevisionsPanel poId={poId} revisions={data.revisions ?? []} />
        <LinksPanel poId={poId} links={data.links ?? []} />
        <DocumentsPanel poId={poId} sources={data.sources} />
        <AuditPanel entries={data.audit ?? []} />
      </Stack>
    </PageLayout>
  );
}

/* -------------------------------------------------------------------------- */

function RevisionsPanel({ poId, revisions }: { poId: number; revisions: PoRevision[] }) {
  const regroup = useRegroup(poId);
  return (
    <SectionCard
      title="Revision chain"
      actions={
        <Button
          size="xs"
          variant="subtle"
          loading={regroup.isPending}
          onClick={() => regroup.mutate({ standalone: true })}
        >
          Mark this PO standalone
        </Button>
      }
    >
      {revisions.length === 0 ? (
        <Text size="sm" c="dimmed">
          No sibling orders (same customer + delivery date, or same PO number).
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={640} type="native">
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>PO</Table.Th>
                <Table.Th>Customer</Table.Th>
                <Table.Th>PO date</Table.Th>
                <Table.Th>Delivery</Table.Th>
                <Table.Th ta="right">Total</Table.Th>
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
                    {r.is_revision && (
                      <Badge size="xs" variant="light">
                        rev
                      </Badge>
                    )}
                    {r.status !== "active" && (
                      <Badge size="xs" color={STATUS_COLOR[r.status]} ml={4}>
                        {r.status}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>{r.customer_name}</Table.Td>
                  <Table.Td>{r.po_date}</Table.Td>
                  <Table.Td>{r.delivery_date}</Table.Td>
                  <Table.Td ta="right" style={NUMERIC_STYLE}>
                    {r.total != null ? fmtCurrency(r.total) : "—"}
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="subtle"
                      loading={regroup.isPending}
                      onClick={() => regroup.mutate({ revision_of: r.po_number ?? r.source_file })}
                    >
                      This is a revision of {r.po_number ?? "it"}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {regroup.isSuccess && (
        <Text size="xs" c="dimmed">
          Saved. Grouping is applied on the next extraction run.
        </Text>
      )}
      {regroup.error && (
        <Text size="xs" c="red">
          {(regroup.error as Error).message}
        </Text>
      )}
    </SectionCard>
  );
}

/* -------------------------------------------------------------------------- */

function LinksPanel({ poId, links }: { poId: number; links: PoLink[] }) {
  const [search, setSearch] = useState("");
  const hits = useInvoiceSearch(search);
  const link = useLinkInvoice(poId);
  const unlink = useUnlinkInvoice(poId);

  return (
    <SectionCard title="Invoice links">
      {links.length === 0 ? (
        <Text size="sm" c="dimmed">
          No invoice linked to this PO yet.
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={640} type="native">
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Invoice</Table.Th>
                <Table.Th>Date</Table.Th>
                <Table.Th ta="right">Amount</Table.Th>
                <Table.Th>State</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {links.map((l) => (
                <Table.Tr key={l.invoice_id}>
                  <Table.Td>{l.doc_number ?? l.invoice_id}</Table.Td>
                  <Table.Td>{l.txn_date}</Table.Td>
                  <Table.Td ta="right" style={NUMERIC_STYLE}>
                    {l.total_amt != null ? fmtCurrency(l.total_amt) : "—"}
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      size="xs"
                      color={l.confirmed ? "gpGreen" : l.rejected ? "gray" : "gpGold"}
                      variant="light"
                    >
                      {l.confirmed ? l.match_method : l.rejected ? "rejected" : "pending"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      {l.qbo_url && (
                        <Anchor href={l.qbo_url} target="_blank" rel="noopener" size="xs">
                          Open in QuickBooks ↗
                        </Anchor>
                      )}
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        loading={unlink.isPending}
                        onClick={() => unlink.mutate(l.invoice_id)}
                      >
                        Unlink
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <TextInput
        label="Link another invoice"
        placeholder="invoice number or customer"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      {hits.data && hits.data.length > 0 && (
        <Table.ScrollContainer minWidth={560} type="native">
          <Table>
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
        </Table.ScrollContainer>
      )}
      {link.error && (
        <Text size="xs" c="red">
          {(link.error as Error).message}
        </Text>
      )}
    </SectionCard>
  );
}

/* -------------------------------------------------------------------------- */

function DocumentsPanel({ poId, sources }: { poId: number; sources?: PoSources }) {
  const { data: docs } = usePoDocuments(poId);
  const capture = useCaptureDocs(poId);
  const upload = useUploadDoc(poId);
  const del = useDeleteDoc(poId);
  const result = capture.data;

  return (
    <SectionCard title="Documents">
      {sources?.gmail_thread_url && (
        <Anchor href={sources.gmail_thread_url} target="_blank" rel="noopener" size="sm">
          Email thread ↗
        </Anchor>
      )}

      <Group gap="xs">
        <Button size="xs" variant="light" loading={capture.isPending} onClick={() => capture.mutate(["gmail"])}>
          Capture from Gmail
        </Button>
        <Button size="xs" variant="light" loading={capture.isPending} onClick={() => capture.mutate(["qbo"])}>
          Capture from QuickBooks
        </Button>
        <Button size="xs" variant="subtle" component="label" loading={upload.isPending}>
          Upload a file
          <input
            type="file"
            hidden
            onChange={(e) => {
              const f = e.currentTarget.files?.[0];
              if (f) upload.mutate(f);
              e.currentTarget.value = "";
            }}
          />
        </Button>
      </Group>

      {result && (
        <Text size="xs" c="dimmed">
          {[result.gmail?.note, result.qbo?.note].filter(Boolean).join(" ")}
          {[...(result.gmail?.skipped ?? []), ...(result.qbo?.skipped ?? [])].length > 0 &&
            ` (${[...(result.gmail?.skipped ?? []), ...(result.qbo?.skipped ?? [])].join("; ")})`}
        </Text>
      )}
      {capture.error && (
        <Text size="xs" c="red">
          {(capture.error as Error).message}
        </Text>
      )}
      {upload.error && (
        <Text size="xs" c="red">
          {(upload.error as Error).message}
        </Text>
      )}

      {!docs || docs.length === 0 ? (
        <Text size="sm" c="dimmed">
          No PDFs captured yet. Use the buttons above to pull them from Gmail / QuickBooks.
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={720} type="native">
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Kind</Table.Th>
                <Table.Th>File</Table.Th>
                <Table.Th>Source</Table.Th>
                <Table.Th ta="right">Size</Table.Th>
                <Table.Th>Captured</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {docs.map((d) => (
                <Table.Tr key={d.id}>
                  <Table.Td>
                    <Badge size="xs" variant="light">
                      {DOC_KIND_LABEL[d.kind]}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Anchor component="button" type="button" onClick={() => openDocument(poId, d.id)}>
                      {d.filename}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{d.source}</Table.Td>
                  <Table.Td ta="right" style={NUMERIC_STYLE}>
                    {(d.byte_size / 1024).toFixed(0)} KB
                  </Table.Td>
                  <Table.Td>{d.captured_at?.slice(0, 16).replace("T", " ") ?? "—"}</Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Button size="xs" variant="subtle" onClick={() => openDocument(poId, d.id)}>
                        View
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        loading={del.isPending}
                        onClick={() => del.mutate(d.id)}
                      >
                        Delete
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </SectionCard>
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
    <SectionCard
      title={`Audit trail (${entries.length})`}
      actions={
        <Button size="xs" variant="subtle" onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Show"}
        </Button>
      }
    >
      <Collapse in={open}>
        {entries.length === 0 ? (
          <Text size="sm" c="dimmed">
            No recorded changes.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={640} type="native">
            <Table fz="xs">
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
                      <Code>{e.delta}</Code>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Collapse>
    </SectionCard>
  );
}
