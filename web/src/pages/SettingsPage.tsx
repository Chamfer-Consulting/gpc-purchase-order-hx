import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import {
  useConnect,
  useConnections,
  useDisconnect,
  useQboSyncNow,
  type ConnectionsStatus,
} from "@/api/connections";
import { useBackfillDocs } from "@/api/poDocs";
import {
  useHiddenInvoices,
  useSetInvoiceHidden,
  useSetVisible,
  useVisibility,
  type VisibilityDim,
} from "@/api/settings";
import { useMe, type Role } from "@/api/me";
import { useRemoveTeamMember, useSetTeamMember, useTeam } from "@/api/team";
import { confirmAction } from "@/lib/modals";
import { notifyError, notifySuccess } from "@/lib/notify";
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
        {roleKnown && canAdmin && <TeamCard />}
      </Stack>
    </PageLayout>
  );
}

const ROLE_DATA = [
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Admin" },
];

function whenText(m: {
  last_sign_in_at: string | null;
  has_account: boolean;
  has_role: boolean;
}): string {
  if (m.last_sign_in_at) return `last sign-in ${m.last_sign_in_at.slice(0, 10)}`;
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

  const rows = data ?? [];
  const adminCount = rows.filter((r) => r.effective_role === "admin").length;

  function grant(target: string, r: Role, existingNote?: string | null) {
    setMember.mutate(
      { email: target, role: r, note: existingNote },
      { onError: (err) => notifyError(err) },
    );
  }

  function add() {
    const e = email.trim().toLowerCase();
    if (!e.includes("@")) return;
    setMember.mutate(
      { email: e, role },
      {
        onSuccess: () => {
          notifySuccess(`${e} set to ${role}.`);
          setEmail("");
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
                  <Table.Th w={230}>Role</Table.Th>
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
                            {!m.allowed && (
                              <Badge size="xs" color="red" variant="light">
                                no access
                              </Badge>
                            )}
                            {m.allowed && !m.has_role && (
                              <Badge size="xs" color="gray" variant="light">
                                default
                              </Badge>
                            )}
                            <Text size="xs" c="dimmed">
                              {whenText(m)}
                            </Text>
                          </Group>
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <SegmentedControl
                          size="xs"
                          value={m.effective_role ?? ""}
                          disabled={lastAdmin || setMember.isPending}
                          onChange={(v) => grant(m.email, v as Role, m.note)}
                          data={ROLE_DATA}
                        />
                        {!m.allowed && (
                          <Text size="xs" c="dimmed" mt={2}>
                            off-domain — pick a role to grant access
                          </Text>
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
            <SegmentedControl
              size="xs"
              value={role}
              onChange={(v) => setRole(v as Role)}
              data={ROLE_DATA}
            />
            <Button size="xs" onClick={add} loading={setMember.isPending} disabled={!email.includes("@")}>
              Save
            </Button>
          </Group>
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
      ) : (
        <VisibilityList key={dim} dim={dim} />
      )}
    </SectionCard>
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
                <Table.Th>Invoice</Table.Th>
                <Table.Th>Customer</Table.Th>
                <Table.Th>Date</Table.Th>
                <Table.Th ta="right">Total</Table.Th>
                <Table.Th>Reason</Table.Th>
                <Table.Th w={80} />
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

function DocumentsCard() {
  const { canEdit } = useMe();
  const backfill = useBackfillDocs();
  const r = backfill.data;

  return (
    <SectionCard
      title="Document capture"
      subtitle="Pulls the emailed PO PDF (Gmail) and the invoice PDF (QuickBooks) onto each PO. Runs nightly; use this to fill gaps now. Idempotent."
    >
      <Group>
        <Button
          size="xs"
          disabled={!canEdit}
          onClick={() => backfill.mutate({ sources: ["gmail", "qbo"] })}
          loading={backfill.isPending}
        >
          Backfill missing PDFs
        </Button>
        <Button
          size="xs"
          variant="default"
          disabled={!canEdit}
          onClick={() => backfill.mutate({ sources: ["gmail"] })}
          loading={backfill.isPending}
        >
          Gmail only
        </Button>
        <Button
          size="xs"
          variant="default"
          disabled={!canEdit}
          onClick={() => backfill.mutate({ sources: ["qbo"] })}
          loading={backfill.isPending}
        >
          QuickBooks only
        </Button>
      </Group>
      {r && (
        <Stack gap={2}>
          {(["gmail", "qbo"] as const).map((k) =>
            r[k] ? (
              <Text key={k} size="xs" c="dimmed">
                {k}: {r[k]!.captured} captured across {r[k]!.scanned} PO(s), {r[k]!.failed} failed,{" "}
                {r[k]!.remaining} still to do.
              </Text>
            ) : null,
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
            {qbo.last_synced_at
              ? `last sync ${qbo.last_synced_at.slice(0, 16).replace("T", " ")}`
              : "never synced"}
          </Text>
          {qbo.auto_sync_error && (
            <Alert color="red" variant="light">
              Daily auto-sync is failing: {qbo.auto_sync_error}
            </Alert>
          )}
          {qbo.auto_synced_at && !qbo.auto_sync_error && (
            <Text size="xs" c="dimmed">
              Auto-sync last ran {qbo.auto_synced_at.slice(0, 16).replace("T", " ")} UTC
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
            {gmail.last_synced_at
              ? ` · last scan ${gmail.last_synced_at.slice(0, 16).replace("T", " ")}`
              : " · never scanned"}
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
