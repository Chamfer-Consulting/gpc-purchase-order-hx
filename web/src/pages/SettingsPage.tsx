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
  Stack,
  Switch,
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
import { useHiddenProducts, useSetHidden } from "@/api/settings";
import { useMe } from "@/api/me";
import { confirmAction } from "@/lib/modals";
import { notifySuccess } from "@/lib/notify";
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
        <ProductVisibilityCard />
      </Stack>
    </PageLayout>
  );
}

function ProductVisibilityCard() {
  const { data, isLoading, error, refetch } = useHiddenProducts();
  const { canEdit } = useMe();
  const setHidden = useSetHidden();
  const [q, setQ] = useState("");

  const shown = useMemo(() => {
    const rows = data ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((r) => r.product_name.toLowerCase().includes(needle))
      : rows;
    // Stable order (most-used first) so toggling a switch doesn't make the row jump.
    return [...filtered].sort((a, b) => b.n_lines - a.n_lines || a.product_name.localeCompare(b.product_name));
  }, [data, q]);

  const hiddenCount = (data ?? []).filter((r) => r.hidden).length;

  return (
    <SectionCard
      title="Product visibility"
      subtitle={`Hidden products are excluded from every analytics page and the reference-price table. ${hiddenCount} hidden now.`}
    >
      <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
        {data && (
          <>
            <TextInput
              size="xs"
              aria-label="Filter products"
              placeholder="Filter products…"
              value={q}
              onChange={(e) => setQ(e.currentTarget.value)}
            />
            <ScrollArea.Autosize mah={320}>
              <Stack gap={2}>
                {shown.map((r) => (
                  <Group key={r.product_name} justify="space-between" wrap="nowrap">
                    <Text size="sm" truncate>
                      {r.product_name}{" "}
                      <Text span size="xs" c="dimmed">
                        ({r.n_lines} lines)
                      </Text>
                    </Text>
                    <Switch
                      size="xs"
                      aria-label={`Hide ${r.product_name}`}
                      disabled={!canEdit}
                      checked={r.hidden}
                      onChange={(e) =>
                        setHidden.mutate({
                          product_name: r.product_name,
                          hidden: e.currentTarget.checked,
                        })
                      }
                    />
                  </Group>
                ))}
                {shown.length === 0 && (
                  <Text size="xs" c="dimmed">
                    No matches.
                  </Text>
                )}
              </Stack>
            </ScrollArea.Autosize>
          </>
        )}
      </QueryBoundary>
    </SectionCard>
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
