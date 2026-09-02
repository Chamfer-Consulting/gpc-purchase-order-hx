import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, Box, Loader, Paper, Stack, Text } from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import {
  useReconcileConfirm,
  useReconcilePo,
  useReconcileQueue,
  useReconcileReject,
  type Stage,
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
import { Workbench } from "@/components/reconcile/Workbench";
import { blockingStage, STAGE_ORDER } from "@/components/reconcile/state";
import { useIsMobile } from "@/hooks/useIsMobile";

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
  const qStage = items.find((i) => i.po_id === poId)?.stage;

  // session progress: everything we've ever seen in the queue, minus what's left
  const everSeen = useRef(new Set<number>());
  items.forEach((i) => everSeen.current.add(i.po_id));
  const cleared = useMemo(() => {
    const left = new Set(items.map((i) => i.po_id));
    return [...everSeen.current].filter((id) => !left.has(id)).length;
  }, [items]);

  // which stage the workbench is showing; lands on whatever blocks each PO
  const [focus, setFocus] = useState<Stage>("extraction");
  useEffect(() => {
    if (view.data) setFocus(blockingStage(view.data, qStage));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poId, view.data?.header.id]);

  useEffect(() => {
    if (queue.isLoading || items.length === 0) return;
    const stillQueued = poId != null && items.some((i) => i.po_id === poId);
    if (!stillQueued) nav(`/reconcile/${items[0].po_id}`, { replace: true });
  }, [poId, items, queue.isLoading, nav]);

  const go = (delta: number) => {
    if (!items.length) return;
    const next = idx < 0 ? 0 : Math.min(Math.max(idx + delta, 0), items.length - 1);
    nav(`/reconcile/${items[next].po_id}`);
  };
  const cycleFocus = (delta: number) => {
    const i = STAGE_ORDER.indexOf(focus);
    setFocus(STAGE_ORDER[(i + delta + STAGE_ORDER.length) % STAGE_ORDER.length]);
  };

  const setVerdict = (v: "is_po" | "not_po" | "needs_fix") => {
    if (!canEdit || !view.data) return;
    const ext = view.data.extraction;
    upsert.mutate({ target_kind: ext.target_kind, target_key: ext.target_key, verdict: v, revision_of: null });
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
    ["[", () => cycleFocus(-1)],
    ["]", () => cycleFocus(1)],
    ["1", () => setVerdict("is_po")],
    ["2", () => setVerdict("not_po")],
    ["3", () => setVerdict("needs_fix")],
    ["y", () => matchFirst("confirm")],
    ["n", () => matchFirst("reject")],
  ]);

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      width="full"
    >
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
          {queue.isLoading ? (
            <Loader size="sm" m="md" />
          ) : queue.error ? (
            <ErrorState error={queue.error} onRetry={() => void queue.refetch()} compact />
          ) : (
            <Queue
              items={items}
              counts={queue.data!.counts}
              selected={poId}
              cleared={cleared}
              onSelect={(id) => nav(`/reconcile/${id}`)}
            />
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
            <Stack gap="md">
              {upsert.isError && (
                <Alert color="red" variant="light">
                  {errorMessage(upsert.error)}
                </Alert>
              )}
              {view.data.header.error && (
                <ExtractionFailureCard poId={poId} error={view.data.header.error} canEdit={canEdit} />
              )}
              <Workbench
                view={view.data}
                poId={poId}
                focus={focus}
                onFocus={setFocus}
                onSkip={() => go(1)}
              />
            </Stack>
          ) : null}
        </div>
      </Box>
    </PageLayout>
  );
}
