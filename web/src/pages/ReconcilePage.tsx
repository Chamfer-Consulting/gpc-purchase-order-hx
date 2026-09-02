import { useEffect, useMemo } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import {
  useReconcileConfirm,
  useReconcilePo,
  useReconcileQueue,
  useReconcileReject,
} from "@/api/reconcile";
import { useUpsertDecision } from "@/api/review";
import { useMe } from "@/api/me";
import { useRealtimeInvalidate } from "@/lib/realtime";
import { errorMessage } from "@/lib/errors";
import { PageLayout } from "@/components/PageLayout";
import { ErrorState } from "@/components/ErrorState";
import { pageMeta } from "@/nav";
import { ExtractionFailureCard } from "@/components/po/ExtractionFailureCard";
import { Queue } from "@/components/reconcile/Queue";
import { useIsMobile } from "@/hooks/useIsMobile";
import { StageExtraction } from "@/components/reconcile/StageExtraction";
import { StageLifecycle } from "@/components/reconcile/StageLifecycle";
import { StageMatch } from "@/components/reconcile/StageMatch";

export function ReconcilePage() {
  const meta = pageMeta("/reconcile")!;
  const { poId: poIdParam } = useParams();
  const nav = useNavigate();
  const poId = poIdParam ? Number(poIdParam) : null;
  const { canEdit } = useMe();

  const queue = useReconcileQueue();
  const isMobile = useIsMobile();
  const view = useReconcilePo(poId);
  const upsert = useUpsertDecision();
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();

  useRealtimeInvalidate("purchase_orders", ["reconcile-queue", "reconcile-po"]);
  useRealtimeInvalidate("po_invoice_links", ["reconcile-queue", "reconcile-po"]);
  useRealtimeInvalidate("extraction_reviews", ["reconcile-queue", "reconcile-po"]);

  const items = queue.data?.items ?? [];
  const idx = useMemo(() => items.findIndex((i) => i.po_id === poId), [items, poId]);

  // Auto-select the first item once the queue loads, and — after a decision /
  // status change drops the current PO out of the queue — advance to the next
  // thing to deal with (top of the queue = highest priority).
  useEffect(() => {
    if (queue.isLoading || items.length === 0) return;
    const stillQueued = poId != null && items.some((i) => i.po_id === poId);
    if (!stillQueued) {
      nav(`/reconcile/${items[0].po_id}`, { replace: true });
    }
  }, [poId, items, queue.isLoading, nav]);

  const go = (delta: number) => {
    if (!items.length) return;
    const next = idx < 0 ? 0 : Math.min(Math.max(idx + delta, 0), items.length - 1);
    nav(`/reconcile/${items[next].po_id}`);
  };

  const setVerdict = (v: "is_po" | "not_po" | "needs_fix") => {
    if (!canEdit || !view.data) return;
    const ext = view.data.extraction;
    upsert.mutate({
      target_kind: ext.target_kind,
      target_key: ext.target_key,
      verdict: v,
      revision_of: null,
    });
  };

  const matchFirst = (action: "confirm" | "reject") => {
    if (!canEdit || !view.data?.candidates.length) return;
    const inv = view.data.candidates[0].invoice_id;
    (action === "confirm" ? confirm : reject).mutate({ po_id: poId!, invoice_id: inv });
  };

  useHotkeys([
    ["j", () => go(1)],
    ["k", () => go(-1)],
    ["ArrowDown", () => go(1)],
    ["ArrowUp", () => go(-1)],
    ["1", () => setVerdict("is_po")],
    ["2", () => setVerdict("not_po")],
    ["3", () => setVerdict("needs_fix")],
    ["y", () => matchFirst("confirm")],
    ["n", () => matchFirst("reject")],
  ]);

  const c = queue.data?.counts;

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      width="full"
    >
      <Group gap="xs" mb="xs">
        {c && (
          <>
            <Badge variant="light" color="gpGold">
              {c.extraction} extraction
            </Badge>
            <Badge variant="light" color="gpGreen">
              {c.match} match
            </Badge>
            {c.unlinked_no_candidate > 0 && (
              <Text size="xs" c="dimmed">
                + {c.unlinked_no_candidate} unlinked with no candidate — run matching
              </Text>
            )}
          </>
        )}
        <Text size="xs" c="dimmed" ml="auto">
          <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd> verdict ·{" "}
          <kbd>y</kbd>/<kbd>n</kbd> match
        </Text>
      </Group>

      <Box
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "minmax(230px, 288px) minmax(0, 1fr)",
          gap: "var(--mantine-spacing-lg)",
          alignItems: "start",
        }}
      >
        <Paper
          withBorder
          radius="md"
          p="xs"
          bg="var(--gp-surface)"
          style={isMobile ? undefined : { position: "sticky", top: 8 }}
        >
          <Group justify="space-between" px={6} pb={4}>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              Queue
            </Text>
            <Text size="xs" c="dimmed">
              {idx >= 0 ? `${idx + 1} / ${items.length}` : items.length}
            </Text>
          </Group>
          {queue.isLoading ? (
            <Loader size="sm" m="md" />
          ) : queue.error ? (
            <ErrorState error={queue.error} onRetry={() => void queue.refetch()} compact />
          ) : (
            <Queue items={items} selected={poId} onSelect={(id) => nav(`/reconcile/${id}`)} />
          )}
        </Paper>

        <div style={{ minWidth: 0 }}>
          {!queue.isLoading && items.length === 0 ? (
            <Text c="dimmed" p="xl" ta="center">
              Nothing needs reconciling. 🎉
            </Text>
          ) : poId == null ? (
            <Text c="dimmed" p="xl" ta="center">
              Select an order from the queue.
            </Text>
          ) : view.isLoading ? (
            <Loader />
          ) : view.error ? (
            <ErrorState error={view.error} onRetry={() => void view.refetch()} />
          ) : view.data ? (
            <Stack gap="lg">
              <Group justify="space-between" wrap="nowrap">
                <div>
                  <Title order={2} fz={20}>
                    PO {view.data.header.po_number ?? poId}
                  </Title>
                  <Text size="sm" c="dimmed">
                    {view.data.header.customer_name ?? "—"} · {view.data.header.source_file}
                  </Text>
                </div>
                <Anchor component={Link} to={`/po/${poId}`} size="sm">
                  Full editor →
                </Anchor>
              </Group>

              {upsert.isError && (
                <Alert color="red" variant="light">
                  {errorMessage(upsert.error)}
                </Alert>
              )}

              {view.data.header.error && (
                <ExtractionFailureCard
                  poId={poId}
                  error={view.data.header.error}
                  canEdit={canEdit}
                />
              )}

              <StageExtraction view={view.data} />
              <StageLifecycle view={view.data} />
              <StageMatch view={view.data} />
            </Stack>
          ) : null}
        </div>
      </Box>
    </PageLayout>
  );
}
