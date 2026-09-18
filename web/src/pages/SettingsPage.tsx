import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Chip,
  CloseButton,
  Code,
  Collapse,
  Divider,
  Group,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPencil,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import {
  useConnect,
  useConnections,
  useDisconnect,
  useQboSyncNow,
  type ConnectionsStatus,
} from "@/api/connections";
import { useBackfillDocs, useDocStorageStatus, type BackfillBucket } from "@/api/poDocs";
import {
  useCustomerAliases,
  useDeleteCustomerAlias,
  useHiddenInvoices,
  useRenameCustomerCanonical,
  useSetCustomerAlias,
  useSetInvoiceHidden,
  useSetVisible,
  useVisibility,
  type VisibilityDim,
} from "@/api/settings";
import { useMe, type Role } from "@/api/me";
import { useRemoveTeamMember, useSetTeamMember, useTeam } from "@/api/team";
import {
  useCreateYieldEmployee,
  useCreateYieldLink,
  useCreateYieldProduct,
  useDeleteYieldEmployee,
  useDeleteYieldLink,
  useDeleteYieldProduct,
  useUpdateYieldEmployee,
  useUpdateYieldProduct,
  useYieldEmployees,
  useYieldLinks,
  useYieldProducts,
  useYieldSalesProductNames,
  type YieldEmployee,
  type YieldProduct,
} from "@/api/yields";
import { fmtDateOnly, fmtDateTime } from "@/lib/datetime";
import { confirmAction, promptReason } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
import { EXTERNAL_VIEWABLE_PAGES } from "@/nav";
import { EmptyState } from "@/components/EmptyState";
import { PageLayout } from "@/components/PageLayout";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { pageMeta } from "@/nav";

const CALLBACK_MESSAGES: Record<string, { color: string; text: string }> = {
  qbo_ok: { color: "gpGreen", text: "QuickBooks connected." },
  gmail_ok: { color: "gpGreen", text: "Gmail connected." },
  qbo_error: { color: "red", text: "QuickBooks connection failed — try again." },
  gmail_error: { color: "red", text: "Gmail connection failed — try again." },
  qbo_state_mismatch: {
    color: "red",
    text: "QuickBooks: security check failed — start the connection again.",
  },
  gmail_state_mismatch: {
    color: "red",
    text: "Gmail: security check failed — start the connection again.",
  },
};

function StatusBadge({ connected, label }: { connected: boolean; label?: string }) {
  return connected ? (
    <Badge color="gpGreen" variant="light">
      Connected{label ? ` · ${label}` : ""}
    </Badge>
  ) : (
    <Badge color="gray" variant="light">
      Not connected
    </Badge>
  );
}

export function SettingsPage() {
  const { data, isLoading, error, refetch } = useConnections();
  const { canEdit, canAdmin, roleKnown } = useMe();
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const callback = sp.get("connect");
  const meta = pageMeta("/settings")!;

  useEffect(() => {
    if (!callback) return;
    // a completed OAuth round-trip changed the connection — reflect it now,
    // not after the 15s staleTime.
    if (callback.endsWith("_ok")) {
      qc.invalidateQueries({ queryKey: ["connections"] });
    }
    // Deps are [callback] only — `sp` is a fresh object every render, so listing it
    // would restart this timer on any re-render inside the 6s window.
    const t = setTimeout(() => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("connect");
          return next;
        },
        { replace: true },
      );
    }, 6000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callback]);

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      width="form"
    >
      <Stack gap="lg">
        {roleKnown && !canEdit && (
          <Alert color="gray" variant="light" title="View-only access">
            You can see the settings below but not change them.
          </Alert>
        )}
        {roleKnown && canEdit && !canAdmin && (
          <Alert color="gray" variant="light" title="Limited access">
            Connecting or disconnecting QuickBooks / Gmail needs the admin role.
          </Alert>
        )}

        {callback && CALLBACK_MESSAGES[callback] && (
          <Alert color={CALLBACK_MESSAGES[callback].color} variant="light">
            {CALLBACK_MESSAGES[callback].text}
          </Alert>
        )}

        <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
          {data && (
            <>
              <QboCard qbo={data.qbo} />
              <GmailCard gmail={data.gmail} />
            </>
          )}
        </QueryBoundary>

        <DocumentsCard />
        <VisibilityCard />
        <ProductYieldsCard />
        {roleKnown && canAdmin && <TeamCard />}
      </Stack>
    </PageLayout>
  );
}

const ROLE_DATA = [
  { value: "field", label: "Field (Yields kiosk only)" },
  { value: "external_viewer", label: "External viewer (page-by-page)" },
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Admin" },
];

/** Toggleable page chips for an external_viewer account — one Chip per
 *  nav.tsx page flagged externalViewable, matching the backend's
 *  EXTERNAL_VIEWABLE_PAGES allow-list exactly. */
function ExternalPagesChips({
  value,
  onChange,
  disabled,
}: {
  value: string[];
  onChange: (pages: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <Chip.Group multiple value={value} onChange={(v) => onChange(v as string[])}>
      <Group gap={4} mt={6}>
        {EXTERNAL_VIEWABLE_PAGES.map((p) => (
          <Chip key={p.to} value={p.to} size="xs" disabled={disabled}>
            {p.label}
          </Chip>
        ))}
      </Group>
    </Chip.Group>
  );
}

function whenText(m: {
  last_sign_in_at: string | null;
  has_account: boolean;
  has_role: boolean;
}): string {
  if (m.last_sign_in_at) return `last sign-in ${fmtDateOnly(m.last_sign_in_at)}`;
  if (m.has_account) return "signed up, no sign-in yet";
  return "invited — hasn't signed in";
}

function TeamCard() {
  const { data, isLoading, error, refetch } = useTeam();
  const { email: myEmail } = useMe();
  const setMember = useSetTeamMember();
  const removeMember = useRemoveTeamMember();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [newPages, setNewPages] = useState<string[]>([]);
  // Only auto-suggest a role while the admin hasn't explicitly picked one for
  // this email — an off-domain address is more likely meant as a restricted
  // external_viewer than a full viewer, but a deliberate manual choice (the
  // footer note below already documents granting any role to an off-domain
  // address as a supported, intentional flow) must never be silently
  // overridden by this suggestion re-running on every keystroke.
  const roleTouchedRef = useRef(false);

  const rows = data?.members ?? [];
  const allowedDomains = data?.allowed_domains ?? [];
  const adminCount = rows.filter((r) => r.effective_role === "admin").length;
  const newEmailDomain = email.trim().toLowerCase().split("@")[1];
  const newEmailOffDomain = !!newEmailDomain && !allowedDomains.includes(newEmailDomain);

  useEffect(() => {
    if (roleTouchedRef.current || !newEmailDomain) return;
    setRole(newEmailOffDomain ? "external_viewer" : "viewer");
  }, [newEmailDomain, newEmailOffDomain]);

  function grant(target: string, r: Role, existingNote?: string | null, pages?: string[]) {
    setMember.mutate(
      { email: target, role: r, note: existingNote, external_pages: pages },
      { onError: (err) => notifyError(err) },
    );
  }

  function add() {
    const e = email.trim().toLowerCase();
    if (!e.includes("@")) return;
    setMember.mutate(
      { email: e, role, external_pages: newPages },
      {
        onSuccess: () => {
          notifySuccess(`${e} set to ${role}.`);
          setEmail("");
          setNewPages([]);
          setRole("viewer");
          roleTouchedRef.current = false;
        },
        onError: (err) => notifyError(err),
      },
    );
  }

  return (
    <SectionCard
      title="Team"
      subtitle="Everyone with a login or a granted role. viewer = read-only · editor = edit POs / invoice matches · admin = + status changes, delete, connections, reference prices, this list. A signed-in user with no role runs as viewer; “no access” means their email isn't allowed."
    >
      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        <Stack gap="sm">
          <Table.ScrollContainer minWidth={560} type="native">
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>User</Table.Th>
                  <Table.Th w={280}>Role</Table.Th>
                  <Table.Th w={64} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((m) => {
                  const isSelf = m.email.toLowerCase() === (myEmail ?? "").toLowerCase();
                  const lastAdmin = m.effective_role === "admin" && adminCount === 1;
                  return (
                    <Table.Tr key={m.email} style={!m.allowed ? { opacity: 0.7 } : undefined}>
                      <Table.Td>
                        <Stack gap={0}>
                          <Text size="sm">
                            {m.email}
                            {isSelf && (
                              <Text span c="dimmed" size="xs">
                                {" "}
                                (you)
                              </Text>
                            )}
                          </Text>
                          <Group gap={6}>
                            <Text size="xs" c="dimmed">
                              {whenText(m)}
                            </Text>
                          </Group>
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Select
                          size="xs"
                          w={200}
                          value={m.effective_role ?? ""}
                          disabled={lastAdmin || setMember.isPending}
                          onChange={(v) => v && grant(m.email, v as Role, m.note, m.external_pages)}
                          data={ROLE_DATA}
                          allowDeselect={false}
                        />
                        {!m.allowed && (
                          <Text size="xs" c="dimmed" mt={2}>
                            off-domain — pick a role to grant access
                          </Text>
                        )}
                        {m.effective_role === "external_viewer" && (
                          <ExternalPagesChips
                            value={m.external_pages}
                            disabled={setMember.isPending}
                            onChange={(pages) => grant(m.email, "external_viewer", m.note, pages)}
                          />
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          disabled={isSelf || lastAdmin || !m.has_role || removeMember.isPending}
                          onClick={() =>
                            confirmAction({
                              title: `Remove ${m.email}'s role?`,
                              body: m.allowed
                                ? "They drop back to the default (viewer)."
                                : "They lose access entirely on their next request.",
                              confirmLabel: "Remove role",
                              confirmColor: "red",
                              onConfirm: () =>
                                removeMember.mutate(m.email, {
                                  onSuccess: () => notifySuccess(`${m.email}: role removed.`),
                                  onError: (err) => notifyError(err),
                                }),
                            })
                          }
                        >
                          Remove
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>

          <Stack gap={4}>
            <Group gap="xs" align="flex-end">
              <TextInput
                label="Add / set someone by email"
                placeholder="name@garfieldproduce.com"
                size="xs"
                w={280}
                value={email}
                onChange={(e) => setEmail(e.currentTarget.value)}
                onKeyDown={(e) => e.key === "Enter" && add()}
              />
              <Select
                size="xs"
                w={200}
                value={role}
                onChange={(v) => {
                  if (!v) return;
                  roleTouchedRef.current = true;
                  setRole(v as Role);
                }}
                data={ROLE_DATA}
                allowDeselect={false}
              />
              <Button size="xs" onClick={add} loading={setMember.isPending} disabled={!email.includes("@")}>
                Save
              </Button>
            </Group>
            {newEmailOffDomain && !roleTouchedRef.current && (
              <Text size="xs" c="dimmed">
                {newEmailDomain} isn't a sign-in-approved domain — defaulted to External viewer. Pick
                pages below, or choose a different role.
              </Text>
            )}
            {role === "external_viewer" && (
              <ExternalPagesChips value={newPages} onChange={setNewPages} disabled={setMember.isPending} />
            )}
          </Stack>
          <Text size="xs" c="dimmed">
            Sign-in domains (<Code>garfieldproduce.com</Code>, <Code>adelantecenter.org</Code>) are set
            on the API as <Code>ALLOWED_EMAIL_DOMAINS</Code>. Giving someone a role here also lets an
            off-domain address in.
          </Text>
        </Stack>
      </QueryBoundary>
    </SectionCard>
  );
}

type VisTab = VisibilityDim | "invoices";

function VisibilityCard() {
  const [dim, setDim] = useState<VisTab>("products");
  return (
    <SectionCard
      title="Visibility"
      subtitle="Hidden products, customers and invoices are dropped from every analytics page (and hidden products from the reference-price table). Invoices are excluded from the Data Quality → Unsent invoices queue."
      actions={
        <SegmentedControl
          size="xs"
          value={dim}
          onChange={(v) => setDim(v as VisTab)}
          data={[
            { value: "products", label: "Products" },
            { value: "customers", label: "Customers" },
            { value: "invoices", label: "Invoices" },
          ]}
        />
      }
    >
      {dim === "invoices" ? (
        <HiddenInvoicesList />
      ) : dim === "customers" ? (
        <Stack gap="md">
          <CustomerAliasPanel />
          <Divider label="Hide / show from analytics" labelPosition="left" />
          <VisibilityList key="customers" dim="customers" />
        </Stack>
      ) : (
        <VisibilityList key={dim} dim={dim} />
      )}
    </SectionCard>
  );
}

/** One canonical company name per customer — buyer spellings folded. Sits in
 *  Settings → Visibility → Customers so all "who is this customer" controls are
 *  in one place. */
function CustomerAliasPanel() {
  const { data, isLoading, error, refetch } = useCustomerAliases();
  const { canEdit } = useMe();
  const setAlias = useSetCustomerAlias();
  const del = useDeleteCustomerAlias();
  const rename = useRenameCustomerCanonical();

  const [spelling, setSpelling] = useState<string | null>(null);
  const [company, setCompany] = useState<string | null>(null);

  const groups = data?.groups ?? [];
  const unaliased = data?.unaliased ?? [];
  const canonicals = data?.canonicals ?? [];

  const doRename = (from: string) =>
    promptReason({
      title: "Rename company",
      description:
        "Every spelling mapped to this company follows the new name. Renaming to a name that already exists merges the two.",
      label: "Company name",
      placeholder: from,
      confirmLabel: "Rename",
      required: true,
      onSubmit: (v) => {
        const to = (v ?? "").trim();
        if (to && to !== from) {
          rename.mutate(
            { from_canonical: from, to_canonical: to },
            { onSuccess: () => notifySuccess(`Renamed to “${to}”.`), onError: (e) => notifyError(e) },
          );
        }
      },
    });

  return (
    <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
      <Stack gap="xs">
        <Text size="xs" c="dimmed">
          A PO is often emailed by a buyer — a person, not the customer. Map every spelling (buyer
          names included) to the one company it belongs to. The company name is what shows across the
          app, and what an invoice is matched against.
        </Text>

        {groups.length === 0 ? (
          <Text size="sm" c="dimmed" py="xs">
            No customers fold to a shared name yet. Map one below.
          </Text>
        ) : (
          <Stack gap={2}>
            {groups.map((g) => (
              <div
                key={g.canonical}
                style={{
                  borderTop: "1px solid var(--mantine-color-default-border)",
                  paddingTop: 6,
                  paddingBottom: 4,
                }}
              >
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <Text size="sm" fw={600} truncate>
                    {g.canonical}
                  </Text>
                  <Group gap={4} wrap="nowrap" style={{ flex: "none" }}>
                    <Text size="xs" c="dimmed">
                      {g.aliases.length} spelling{g.aliases.length === 1 ? "" : "s"}
                    </Text>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      disabled={!canEdit}
                      onClick={() => doRename(g.canonical)}
                    >
                      Rename
                    </Button>
                  </Group>
                </Group>
                <Group gap={4} mt={4}>
                  {g.aliases.map((a) => (
                    <Badge
                      key={a.name}
                      size="sm"
                      variant="light"
                      color={a.source === "manual" ? "gpGreen" : "gray"}
                      rightSection={
                        canEdit ? (
                          <CloseButton
                            size="xs"
                            aria-label={`Unmap ${a.name}`}
                            onClick={() =>
                              del.mutate(a.name, {
                                onSuccess: () => notifySuccess(`Unmapped “${a.name}”.`),
                                onError: (e) => notifyError(e),
                              })
                            }
                          />
                        ) : undefined
                      }
                    >
                      {a.name}
                    </Badge>
                  ))}
                </Group>
              </div>
            ))}
          </Stack>
        )}

        <Group gap="xs" align="flex-end" wrap="wrap" mt={4}>
          <Select
            label="Spelling"
            size="xs"
            w={220}
            searchable
            placeholder="a name seen on a PO / invoice"
            data={unaliased}
            value={spelling}
            onChange={setSpelling}
            disabled={!canEdit}
            nothingFoundMessage="Every seen spelling is already mapped"
          />
          <Select
            label="means company"
            size="xs"
            w={220}
            searchable
            placeholder="canonical company"
            data={canonicals}
            value={company}
            onChange={setCompany}
            disabled={!canEdit}
          />
          <Button
            size="xs"
            loading={setAlias.isPending}
            disabled={!canEdit || !spelling || !company}
            onClick={() =>
              setAlias.mutate(
                { alias_name: spelling as string, canonical_name: company as string },
                {
                  onSuccess: () => {
                    notifySuccess("Mapped.");
                    setSpelling(null);
                    setCompany(null);
                  },
                  onError: (e) => notifyError(e),
                },
              )
            }
          >
            Map
          </Button>
        </Group>
      </Stack>
    </QueryBoundary>
  );
}

function HiddenInvoicesList() {
  const { data, isLoading, error, refetch } = useHiddenInvoices();
  const { canEdit } = useMe();
  const restore = useSetInvoiceHidden();
  const rows = data ?? [];

  return (
    <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
      {rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          No invoices excluded. Exclude one from Data Quality → “Unsent / auto-generated invoices”.
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={560} type="native">
          <Table verticalSpacing="xs" fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={130}>Invoice</Table.Th>
                <Table.Th>Customer</Table.Th>
                <Table.Th w={110}>Date</Table.Th>
                <Table.Th w={116} ta="right">Total</Table.Th>
                <Table.Th>Reason</Table.Th>
                <Table.Th w={92} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.qbo_invoice_id}>
                  <Table.Td>{r.doc_number ?? r.qbo_invoice_id}</Table.Td>
                  <Table.Td>{r.customer_name ?? "—"}</Table.Td>
                  <Table.Td>{r.txn_date?.slice(0, 10) ?? "—"}</Table.Td>
                  <Table.Td ta="right">
                    {r.total_amt != null ? `$${r.total_amt.toLocaleString()}` : "—"}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {r.reason ?? "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      disabled={!canEdit || restore.isPending}
                      onClick={() =>
                        restore.mutate(
                          { qbo_invoice_id: r.qbo_invoice_id, hidden: false },
                          {
                            onSuccess: () => notifySuccess(`Restored ${r.doc_number ?? r.qbo_invoice_id}.`),
                            onError: (e) => notifyError(e),
                          },
                        )
                      }
                    >
                      Restore
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </QueryBoundary>
  );
}

const UNIT: Record<VisibilityDim, string> = { products: "lines", customers: "invoices" };

function VisibilityList({ dim }: { dim: VisibilityDim }) {
  const { data, isLoading, error, refetch } = useVisibility(dim);
  const { canEdit } = useMe();
  const setVisible = useSetVisible(dim);
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | "visible" | "hidden">("all");

  const rows = data ?? [];
  const hiddenCount = rows.filter((r) => r.hidden).length;
  const visibleCount = rows.length - hiddenCount;

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => (needle ? (r.name ?? "").toLowerCase().includes(needle) : true))
      .filter((r) => (show === "all" ? true : show === "hidden" ? r.hidden : !r.hidden))
      // stable order (most-used first) so toggling a switch never makes a row jump
      .sort((a, b) => b.n_lines - a.n_lines || (a.name ?? "").localeCompare(b.name ?? ""));
  }, [rows, q, show]);

  return (
    <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
      <Group gap="sm" wrap="wrap">
        <Text size="sm" fw={600}>
          <Text span c="var(--gp-status-good)">
            {visibleCount}
          </Text>{" "}
          visible ·{" "}
          <Text span c={hiddenCount ? "orange" : undefined}>
            {hiddenCount}
          </Text>{" "}
          hidden
        </Text>
        <SegmentedControl
          size="xs"
          ml="auto"
          value={show}
          onChange={(v) => setShow(v as typeof show)}
          data={[
            { value: "all", label: "All" },
            { value: "visible", label: "Visible" },
            { value: "hidden", label: "Hidden" },
          ]}
        />
      </Group>

      <TextInput
        size="xs"
        aria-label={`Filter ${dim}`}
        placeholder={`Filter ${dim}…`}
        value={q}
        onChange={(e) => setQ(e.currentTarget.value)}
      />

      <ScrollArea.Autosize mah={360}>
        <Stack gap={0}>
          {shown.map((r) => (
            <Group
              key={r.name}
              justify="space-between"
              wrap="nowrap"
              py={4}
              px={2}
              style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
            >
              <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                <Text size="sm" truncate c={r.hidden ? "dimmed" : undefined}>
                  {r.name}
                </Text>
                <Text span size="xs" c="dimmed" style={{ flex: "none" }}>
                  ({r.n_lines} {UNIT[dim]})
                </Text>
                {/\(deleted/i.test(r.name ?? "") && (
                  <Badge size="xs" color="gray" variant="light" style={{ flex: "none" }}>
                    deleted in QBO
                  </Badge>
                )}
                {r.hidden && (
                  <Badge size="xs" color="orange" variant="light" style={{ flex: "none" }}>
                    hidden
                  </Badge>
                )}
              </Group>
              <Switch
                size="xs"
                aria-label={`${r.hidden ? "Show" : "Hide"} ${r.name}`}
                disabled={!canEdit}
                checked={!r.hidden}
                onChange={(e) => setVisible.mutate({ name: r.name, hidden: !e.currentTarget.checked })}
              />
            </Group>
          ))}
          {shown.length === 0 && (
            <Text size="xs" c="dimmed" py="sm">
              {rows.length === 0 ? `No ${dim} yet.` : "No matches."}
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>
    </QueryBoundary>
  );
}

type DocSrc = "gmail" | "qbo";
const DOC_SRCS: readonly DocSrc[] = ["gmail", "qbo"];
const emptyBucket = (): BackfillBucket => ({
  scanned: 0,
  captured: 0,
  failed: 0,
  remaining: 0,
  errors: [],
  more: false,
});
const sumOf = (a: Partial<Record<DocSrc, BackfillBucket>> | null, k: keyof BackfillBucket) =>
  a ? DOC_SRCS.reduce((n, s) => n + (Number(a[s]?.[k]) || 0), 0) : 0;

function StorageLine() {
  const { data: s } = useDocStorageStatus();
  if (!s) return null;
  if (s.mode === "inline") {
    return (
      <Text size="xs" c="orange">
        PDFs are stored inline in the database — Supabase Storage isn’t configured (set
        SUPABASE_URL + a secret key). {s.counts.total} on file.
      </Text>
    );
  }
  if (s.reachable === false) {
    return (
      <Text size="xs" c="red">
        Supabase Storage is configured but the “{s.bucket}” bucket isn’t reachable: {s.error}.
        New captures will fail until it exists.
      </Text>
    );
  }
  return (
    <Text size="xs" c="dimmed">
      PDFs upload to Supabase Storage (bucket “{s.bucket}”). {s.counts.in_storage} in Storage
      {s.counts.inline ? `, ${s.counts.inline} still inline (run --migrate-storage)` : ""}.
    </Text>
  );
}

function DocumentsCard() {
  const { canEdit } = useMe();
  const backfill = useBackfillDocs();
  const [running, setRunning] = useState<string | null>(null);
  const [acc, setAcc] = useState<Partial<Record<DocSrc, BackfillBucket>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // One button press drives many short backfill calls: each server call has an
  // ~18s budget and returns `more` while work is queued, so we loop until it's
  // drained. (A single whole-catalogue call outruns the request timeout — the
  // browser then shows "Load failed" even though the server keeps going.)
  const run = async (sources: DocSrc[], label: string) => {
    if (running) return;
    setRunning(label);
    setErr(null);
    setDone(false);
    const totals: Partial<Record<DocSrc, BackfillBucket>> = {};
    for (const s of sources) totals[s] = emptyBucket();
    let prevRemaining = Infinity;
    try {
      for (let pass = 0; pass < 40; pass++) {
        const res = await backfill.mutateAsync({ sources, limit: 100, continued: pass > 0 });
        let more = false;
        let capturedThisPass = 0;
        for (const s of sources) {
          const b = res[s];
          if (!b) continue;
          const t = totals[s]!;
          t.scanned += b.scanned;
          t.captured += b.captured;
          t.failed += b.failed;
          t.remaining = b.remaining;
          t.errors = b.errors;
          t.more = b.more;
          capturedThisPass += b.captured;
          if (b.more) more = true;
        }
        setAcc({ ...totals });
        const nowRemaining = sumOf(totals, "remaining");
        if (!more) break;
        // stalled: the only rows left keep erroring — don't spin
        if (capturedThisPass === 0 && nowRemaining >= prevRemaining) break;
        prevRemaining = nowRemaining;
      }
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Backfill failed.");
    } finally {
      setRunning(null);
    }
  };

  const btn = (sources: DocSrc[], label: string, primary = false) => (
    <Button
      size="xs"
      variant={primary ? undefined : "default"}
      disabled={!canEdit || !!running}
      loading={running === label}
      onClick={() => run(sources, label)}
    >
      {label}
    </Button>
  );

  return (
    <SectionCard
      title="Document capture"
      subtitle="Pulls the emailed PO PDF (Gmail) and the invoice PDF (QuickBooks) onto each PO. Runs nightly; use this to fill gaps now. Idempotent."
    >
      <Group>
        {btn(["gmail", "qbo"], "Backfill missing PDFs", true)}
        {btn(["gmail"], "Gmail only")}
        {btn(["qbo"], "QuickBooks only")}
      </Group>
      <StorageLine />
      {running && (
        <Text size="xs" c="dimmed">
          Working… {sumOf(acc, "captured")} captured
          {sumOf(acc, "remaining") ? `, ${sumOf(acc, "remaining")} to go` : ""}.
        </Text>
      )}
      {err && (
        <Text size="xs" c="red">
          {err}
        </Text>
      )}
      {acc && (
        <Stack gap={4}>
          {DOC_SRCS.map((k) => {
            const b = acc[k];
            if (!b) return null;
            const line =
              b.scanned === 0 && b.remaining === 0
                ? `${k}: nothing missing — every eligible PO already has its PDF.`
                : `${k}: ${b.captured} captured` +
                  (b.failed ? `, ${b.failed} failed` : "") +
                  (b.remaining ? `, ${b.remaining} still missing` : "") +
                  (running ? "…" : ".");
            return (
              <div key={k}>
                <Text size="xs" c={b.failed && !b.captured ? "red" : "dimmed"}>
                  {line}
                </Text>
                {b.errors.slice(0, 3).map((e, i) => (
                  <Text key={i} size="xs" c="dimmed" pl="sm" style={{ opacity: 0.8 }}>
                    {e}
                  </Text>
                ))}
                {b.errors.length > 3 && (
                  <Text size="xs" c="dimmed" pl="sm" style={{ opacity: 0.8 }}>
                    …and {b.errors.length - 3} more.
                  </Text>
                )}
              </div>
            );
          })}
          {done && sumOf(acc, "remaining") > 0 && (
            <Text size="xs" c="dimmed">
              {sumOf(acc, "remaining")} couldn’t be captured (reasons above) — the nightly job retries.
            </Text>
          )}
        </Stack>
      )}
    </SectionCard>
  );
}

function QboCard({ qbo }: { qbo: ConnectionsStatus["qbo"] }) {
  const { canEdit, canAdmin } = useMe();
  const connect = useConnect("qbo");
  const disconnect = useDisconnect("qbo");
  const syncNow = useQboSyncNow();

  const confirmDisconnect = () =>
    confirmAction({
      title: "Disconnect QuickBooks?",
      body: "The nightly invoice sync stops until someone reconnects. Existing data is kept.",
      confirmLabel: "Disconnect",
      onConfirm: () =>
        disconnect.mutate(undefined, { onSuccess: () => notifySuccess("QuickBooks disconnected.") }),
    });

  return (
    <SectionCard title="QuickBooks" actions={<StatusBadge connected={!!qbo} label={qbo?.environment} />}>
      {qbo ? (
        <Stack gap={6}>
          <Text size="sm" c="dimmed">
            {canAdmin && (
              <>
                Realm <Code>{qbo.realm_id}</Code>
                {" · "}
              </>
            )}
            {qbo.last_synced_at ? `last sync ${fmtDateTime(qbo.last_synced_at)}` : "never synced"}
          </Text>
          {qbo.auto_sync_error && (
            <Alert color="red" variant="light">
              Daily auto-sync is failing: {qbo.auto_sync_error}
            </Alert>
          )}
          {qbo.auto_synced_at && !qbo.auto_sync_error && (
            <Text size="xs" c="dimmed">
              Auto-sync last ran {fmtDateTime(qbo.auto_synced_at)}
            </Text>
          )}
          <Group mt="xs">
            <Button
              size="xs"
              disabled={!canEdit}
              onClick={() => syncNow.mutate(false)}
              loading={syncNow.isPending}
            >
              Sync now
            </Button>
            <Button
              size="xs"
              variant="default"
              disabled={!canEdit}
              onClick={() => syncNow.mutate(true)}
              loading={syncNow.isPending}
            >
              Full resync
            </Button>
            <Button
              size="xs"
              color="red"
              variant="subtle"
              disabled={!canAdmin}
              onClick={confirmDisconnect}
            >
              Disconnect
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            A full resync pulls the whole invoice history and can take a few minutes.
          </Text>
          {syncNow.data && (
            <Text size="xs" c="dimmed">
              Synced {syncNow.data.items} catalog items, {syncNow.data.synced} invoices
              {syncNow.data.deleted ? `, removed ${syncNow.data.deleted}` : ""}.
            </Text>
          )}
        </Stack>
      ) : (
        <Button
          size="xs"
          disabled={!canAdmin}
          onClick={() => connect.mutate()}
          loading={connect.isPending}
        >
          Connect to QuickBooks
        </Button>
      )}
    </SectionCard>
  );
}

function GmailCard({ gmail }: { gmail: ConnectionsStatus["gmail"] }) {
  const { canAdmin } = useMe();
  const connect = useConnect("gmail");
  const disconnect = useDisconnect("gmail");

  const confirmDisconnect = () =>
    confirmAction({
      title: "Disconnect Gmail?",
      body: "The scheduled extraction can no longer read the mailbox until someone reconnects.",
      confirmLabel: "Disconnect",
      onConfirm: () =>
        disconnect.mutate(undefined, { onSuccess: () => notifySuccess("Gmail disconnected.") }),
    });

  return (
    <SectionCard title="Gmail ingestion" actions={<StatusBadge connected={!!gmail} />}>
      {gmail ? (
        <Stack gap={6}>
          <Text size="sm" c="dimmed">
            {gmail.email_address}
            {gmail.last_synced_at ? ` · last scan ${fmtDateTime(gmail.last_synced_at)}` : " · never scanned"}
          </Text>
          <Text size="xs" c="dimmed">
            Extraction runs on a schedule (GitHub Actions). This just holds the mailbox token.
          </Text>
          <Group mt="xs">
            <Button
              size="xs"
              color="red"
              variant="subtle"
              disabled={!canAdmin}
              onClick={confirmDisconnect}
            >
              Disconnect
            </Button>
          </Group>
        </Stack>
      ) : (
        <Button
          size="xs"
          disabled={!canAdmin}
          onClick={() => connect.mutate()}
          loading={connect.isPending}
        >
          Connect Gmail
        </Button>
      )}
    </SectionCard>
  );
}

// --- Product Yields: harvest catalog + team (moved here from the standalone
// /yields/admin page — same SegmentedControl-tab pattern VisibilityCard above
// already uses for its Products/Customers/Invoices split) ------------------

/** A small inline "add a harvest product" form — editor/admin only. */
function AddProductForm() {
  const create = useCreateYieldProduct();
  const [name, setName] = useState("");
  const [lotPrefix, setLotPrefix] = useState("");

  const submit = () => {
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), lot_code_prefix: lotPrefix.trim() || null },
      {
        onSuccess: () => {
          notifySuccess(`Added "${name.trim()}".`);
          setName("");
          setLotPrefix("");
        },
        onError: (e) => notifyError(e),
      },
    );
  };

  return (
    <Group align="flex-end" gap="xs">
      <TextInput
        label="Add a harvest product"
        placeholder="e.g. Kale - Curly"
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
        style={{ flex: 1 }}
      />
      <TextInput
        label="Lot prefix"
        placeholder="e.g. TK"
        value={lotPrefix}
        onChange={(e) => setLotPrefix(e.currentTarget.value)}
        w={120}
      />
      <Button loading={create.isPending} disabled={!name.trim()} onClick={submit}>
        Add
      </Button>
    </Group>
  );
}

/** A product's sales-SKU links — one row can feed several sold SKUs (sold
 *  fresh + in a blend), and a blend SKU pulls from several yield products, so
 *  this is a genuine many-to-many, not a "pick one" mapping. */
function ProductLinks({ productId }: { productId: number }) {
  const links = useYieldLinks(productId);
  const salesNames = useYieldSalesProductNames();
  const create = useCreateYieldLink();
  const del = useDeleteYieldLink();
  const [selected, setSelected] = useState<string | null>(null);

  const linkedNames = new Set((links.data ?? []).map((l) => l.sales_product_name));
  const salesOptions = (salesNames.data ?? []).filter((n) => !linkedNames.has(n));

  return (
    <Stack gap="xs" py="sm" pl="md">
      <QueryBoundary loading={links.isLoading} error={links.error} onRetry={() => void links.refetch()}>
        <Group gap={6} wrap="wrap">
          {(links.data ?? []).length === 0 && (
            <Text size="xs" c="dimmed">
              Not linked to any sales SKU yet.
            </Text>
          )}
          {(links.data ?? []).map((l) => (
            <Badge
              key={l.id}
              variant="light"
              color="gray"
              rightSection={
                <CloseButton
                  size={12}
                  onClick={() => del.mutate(l.id, { onError: (e) => notifyError(e) })}
                  aria-label={`Unlink ${l.sales_product_name}`}
                />
              }
            >
              {l.sales_product_name}
            </Badge>
          ))}
        </Group>
      </QueryBoundary>
      <Group gap="xs">
        <Select
          placeholder="Link a sales SKU…"
          data={salesOptions}
          value={selected}
          onChange={setSelected}
          searchable
          size="xs"
          w={280}
          disabled={salesNames.isLoading}
        />
        <Button
          size="xs"
          variant="light"
          disabled={!selected}
          loading={create.isPending}
          onClick={() =>
            selected &&
            create.mutate(
              { yield_product_id: productId, sales_product_name: selected },
              { onSuccess: () => setSelected(null), onError: (e) => notifyError(e) },
            )
          }
        >
          Link
        </Button>
      </Group>
    </Stack>
  );
}

function ProductRow({ product, canEdit }: { product: YieldProduct; canEdit: boolean }) {
  const update = useUpdateYieldProduct();
  const del = useDeleteYieldProduct();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(product.name);
  const [lotPrefix, setLotPrefix] = useState(product.lot_code_prefix ?? "");
  const [linksOpen, setLinksOpen] = useState(false);
  // Collapse animates height without unmounting its children, so mounting
  // ProductLinks unconditionally would fire every row's useYieldLinks fetch
  // on page load. Mount it lazily on first expand and leave it mounted after
  // that (rather than un-mounting on every collapse) so the close animation
  // still has content to animate away.
  const [linksMounted, setLinksMounted] = useState(false);

  const cancelEdit = () => {
    setEditing(false);
    setName(product.name);
    setLotPrefix(product.lot_code_prefix ?? "");
  };

  const saveName = () => {
    const trimmedName = name.trim();
    const trimmedPrefix = lotPrefix.trim();
    const patch: { id: number; name?: string; lot_code_prefix?: string | null } = { id: product.id };
    if (trimmedName && trimmedName !== product.name) patch.name = trimmedName;
    if (trimmedPrefix !== (product.lot_code_prefix ?? "")) patch.lot_code_prefix = trimmedPrefix || null;
    if (!("name" in patch) && !("lot_code_prefix" in patch)) {
      cancelEdit();
      return;
    }
    update.mutate(patch, {
      onSuccess: () => {
        notifySuccess("Saved.");
        setEditing(false);
      },
      onError: (e) => {
        notifyError(e);
        setName(product.name);
        setLotPrefix(product.lot_code_prefix ?? "");
      },
    });
  };

  const askDelete = () => {
    confirmAction({
      title: "Delete this product?",
      body: `"${product.name}" will be permanently removed. This only works if no harvest entries reference it yet — if any exist, retire it instead of deleting it.`,
      confirmLabel: "Delete",
      onConfirm: () =>
        del.mutate(product.id, {
          onSuccess: () => notifySuccess("Deleted."),
          onError: (e) => notifyError(e),
        }),
    });
  };

  return (
    <>
      <Table.Tr>
        {canEdit && (
          <Table.Td w={32}>
            <ActionIcon
              size="sm"
              variant="subtle"
              onClick={() => {
                setLinksOpen((v) => !v);
                setLinksMounted(true);
              }}
              aria-label="Sales SKU links"
            >
              {linksOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            </ActionIcon>
          </Table.Td>
        )}
        <Table.Td>
          {editing ? (
            <Group gap={4} wrap="nowrap">
              <TextInput
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                size="xs"
                data-autofocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") cancelEdit();
                }}
              />
              <TextInput
                value={lotPrefix}
                onChange={(e) => setLotPrefix(e.currentTarget.value)}
                placeholder="Lot prefix"
                size="xs"
                w={90}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") cancelEdit();
                }}
              />
              <ActionIcon size="sm" color="gpGreen" variant="light" onClick={saveName} loading={update.isPending}>
                <IconCheck size={14} />
              </ActionIcon>
              <ActionIcon size="sm" variant="subtle" onClick={cancelEdit}>
                <IconX size={14} />
              </ActionIcon>
            </Group>
          ) : (
            <Group gap={6} wrap="nowrap">
              <Text fw={500} c={product.active ? undefined : "dimmed"}>
                {product.name}
              </Text>
              {product.lot_code_prefix && (
                <Badge size="xs" variant="light" color="gray">
                  {product.lot_code_prefix}
                </Badge>
              )}
              {product.has_notes && (
                <Tooltip label="Has an entry note or a grower observation on one of its lots">
                  <Badge size="xs" variant="dot" color="gpGreen">
                    Notes
                  </Badge>
                </Tooltip>
              )}
            </Group>
          )}
        </Table.Td>
        <Table.Td w={120}>
          {canEdit ? (
            <Switch
              checked={product.active}
              label={product.active ? "Active" : "Retired"}
              onChange={(e) =>
                update.mutate(
                  { id: product.id, active: e.currentTarget.checked },
                  { onError: (err) => notifyError(err) },
                )
              }
            />
          ) : (
            <Badge color={product.active ? "gpGreen" : "gray"} variant="light">
              {product.active ? "Active" : "Retired"}
            </Badge>
          )}
        </Table.Td>
        {canEdit && (
          <Table.Td w={72}>
            {!editing && (
              <Group gap={4} wrap="nowrap">
                <ActionIcon size="sm" variant="subtle" onClick={() => setEditing(true)} aria-label="Edit">
                  <IconPencil size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  onClick={askDelete}
                  loading={del.isPending}
                  aria-label="Delete"
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            )}
          </Table.Td>
        )}
      </Table.Tr>
      {canEdit && (
        <Table.Tr>
          <Table.Td colSpan={4} p={0}>
            <Collapse in={linksOpen}>{linksMounted && <ProductLinks productId={product.id} />}</Collapse>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
}

/** Every harvest product — active ones show up on the kiosk's picker; retire
 *  (toggle off) to hide one from the picker without losing its entry
 *  history, or delete it outright while it still has zero entries. Expand a
 *  row (editor/admin only) to manage its sales-SKU links. */
function ProductList({ products, canEdit }: { products: YieldProduct[]; canEdit: boolean }) {
  if (products.length === 0) {
    return <EmptyState label="No harvest products yet" compact />;
  }

  return (
    <Table verticalSpacing="xs">
      <Table.Tbody>
        {products.map((p) => (
          <ProductRow key={p.id} product={p} canEdit={canEdit} />
        ))}
      </Table.Tbody>
    </Table>
  );
}

/** A small inline "add an employee" form — editor/admin only. */
function AddEmployeeForm() {
  const create = useCreateYieldEmployee();
  const [name, setName] = useState("");

  return (
    <Group align="flex-end" gap="xs">
      <TextInput
        label="Add an employee"
        placeholder="e.g. Maria Lopez"
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
        style={{ flex: 1 }}
      />
      <Button
        loading={create.isPending}
        disabled={!name.trim()}
        onClick={() =>
          create.mutate(
            { name: name.trim() },
            {
              onSuccess: () => {
                notifySuccess(`Added "${name.trim()}".`);
                setName("");
              },
              onError: (e) => notifyError(e),
            },
          )
        }
      >
        Add
      </Button>
    </Group>
  );
}

function EmployeeRow({ employee, canEdit }: { employee: YieldEmployee; canEdit: boolean }) {
  const update = useUpdateYieldEmployee();
  const del = useDeleteYieldEmployee();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(employee.name);

  const cancelEdit = () => {
    setEditing(false);
    setName(employee.name);
  };

  const saveName = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === employee.name) {
      cancelEdit();
      return;
    }
    update.mutate(
      { id: employee.id, name: trimmed },
      {
        onSuccess: () => {
          notifySuccess("Renamed.");
          setEditing(false);
        },
        onError: (e) => {
          notifyError(e);
          setName(employee.name);
        },
      },
    );
  };

  const askDelete = () => {
    confirmAction({
      title: "Delete this employee?",
      body: `"${employee.name}" will be removed from the kiosk's picker. Past entries keep whatever name they already have — this doesn't touch entry history.`,
      confirmLabel: "Delete",
      onConfirm: () =>
        del.mutate(employee.id, {
          onSuccess: () => notifySuccess("Deleted."),
          onError: (e) => notifyError(e),
        }),
    });
  };

  return (
    <Table.Tr>
      <Table.Td>
        {editing ? (
          <Group gap={4} wrap="nowrap">
            <TextInput
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              size="xs"
              data-autofocus
              onKeyDown={(e) => {
                if (e.key === "Enter") saveName();
                if (e.key === "Escape") cancelEdit();
              }}
            />
            <ActionIcon size="sm" color="gpGreen" variant="light" onClick={saveName} loading={update.isPending}>
              <IconCheck size={14} />
            </ActionIcon>
            <ActionIcon size="sm" variant="subtle" onClick={cancelEdit}>
              <IconX size={14} />
            </ActionIcon>
          </Group>
        ) : (
          <Text fw={500} c={employee.active ? undefined : "dimmed"}>
            {employee.name}
          </Text>
        )}
      </Table.Td>
      <Table.Td w={120}>
        {canEdit ? (
          <Switch
            checked={employee.active}
            label={employee.active ? "Active" : "Retired"}
            onChange={(e) =>
              update.mutate(
                { id: employee.id, active: e.currentTarget.checked },
                { onError: (err) => notifyError(err) },
              )
            }
          />
        ) : (
          <Badge color={employee.active ? "gpGreen" : "gray"} variant="light">
            {employee.active ? "Active" : "Retired"}
          </Badge>
        )}
      </Table.Td>
      {canEdit && (
        <Table.Td w={72}>
          {!editing && (
            <Group gap={4} wrap="nowrap">
              <ActionIcon size="sm" variant="subtle" onClick={() => setEditing(true)} aria-label="Rename">
                <IconPencil size={14} />
              </ActionIcon>
              <ActionIcon
                size="sm"
                variant="subtle"
                color="red"
                onClick={askDelete}
                loading={del.isPending}
                aria-label="Delete"
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Group>
          )}
        </Table.Td>
      )}
    </Table.Tr>
  );
}

/** The kiosk's "harvested by" roster. Retire to hide from the picker; delete
 *  outright any time — harvested_by stays free text on existing entries
 *  either way, so this never risks entry history. */
function EmployeeList({ employees, canEdit }: { employees: YieldEmployee[]; canEdit: boolean }) {
  if (employees.length === 0) {
    return <EmptyState label="No employees yet" compact />;
  }

  return (
    <Table verticalSpacing="xs">
      <Table.Tbody>
        {employees.map((e) => (
          <EmployeeRow key={e.id} employee={e} canEdit={canEdit} />
        ))}
      </Table.Tbody>
    </Table>
  );
}

type YieldsAdminTab = "products" | "team";

/** Harvest product catalog (+ sales-SKU links) and the kiosk's harvested-by
 *  roster — moved here from the standalone /yields/admin page so every piece
 *  of app configuration lives in one place. */
function ProductYieldsCard() {
  const { canEdit } = useMe();
  const [tab, setTab] = useState<YieldsAdminTab>("products");
  const products = useYieldProducts(true);
  const employees = useYieldEmployees(true);

  return (
    <SectionCard
      title="Product Yields"
      subtitle="The harvest kiosk's product catalog and harvested-by roster."
      actions={
        <SegmentedControl
          size="xs"
          value={tab}
          onChange={(v) => setTab(v as YieldsAdminTab)}
          data={[
            { value: "products", label: "Harvest products" },
            { value: "team", label: "Harvest team" },
          ]}
        />
      }
    >
      {tab === "products" ? (
        <Stack gap="md">
          {canEdit && <AddProductForm />}
          <QueryBoundary
            loading={products.isLoading}
            error={products.error}
            onRetry={() => void products.refetch()}
          >
            <ProductList products={products.data ?? []} canEdit={canEdit} />
          </QueryBoundary>
        </Stack>
      ) : (
        <Stack gap="md">
          {canEdit && <AddEmployeeForm />}
          <QueryBoundary
            loading={employees.isLoading}
            error={employees.error}
            onRetry={() => void employees.refetch()}
          >
            <EmployeeList employees={employees.data ?? []} canEdit={canEdit} />
          </QueryBoundary>
        </Stack>
      )}
    </SectionCard>
  );
}
