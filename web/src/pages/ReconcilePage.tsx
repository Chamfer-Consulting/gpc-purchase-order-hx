import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Box, Loader, Stack, Text } from "@mantine/core";
import { useDisclosure, useHotkeys } from "@mantine/hooks";
import {
  useReconcileConfirm,
  useReconcilePo,
  useReconcileQueue,
  useReconcileReject,
} from "@/api/reconcile";
import { useMe } from "@/api/me";
import { useRealtimeInvalidate } from "@/lib/realtime";
import { PageLayout } from "@/components/PageLayout";
import { ErrorState } from "@/components/ErrorState";
import { pageMeta } from "@/nav";
import { ReviewHeader, type ReviewFilter } from "@/components/reconcile/ReviewHeader";
import { ReviewStream } from "@/components/reconcile/ReviewStream";
import { QueueJump } from "@/components/reconcile/QueueJump";
import { useExtractionDecision, type Verdict } from "@/components/reconcile/extraction";

const FILTER_STAGE: Record<Exclude<ReviewFilter, "all">, string> = {
  verdict: "extraction",
  match: "match",
};

export function ReconcilePage() {
  const meta = pageMeta("/reconcile")!;
  const { poId: poIdParam } = useParams();
  const nav = useNavigate();
  const poId = poIdParam ? Number(poIdParam) : null;
  const { canEdit } = useMe();

  const queue = useReconcileQueue();
  const view = useReconcilePo(poId);
  const confirm = useReconcileConfirm();
  const reject = useReconcileReject();
  const [jumpOpen, jump] = useDisclosure(false);
  const [filter, setFilter] = useState<ReviewFilter>("all");

  useRealtimeInvalidate("purchase_orders", ["reconcile-queue", "reconcile-po"]);
  useRealtimeInvalidate("po_invoice_links", ["reconcile-queue", "reconcile-po"]);
  useRealtimeInvalidate("extraction_reviews", ["reconcile-queue", "reconcile-po"]);

  const items = queue.data?.items ?? [];
  const filtered = useMemo(
    () => (filter === "all" ? items : items.filter((i) => i.stage === FILTER_STAGE[filter])),
    [items, filter],
  );
  const idx = filtered.findIndex((i) => i.po_id === poId);

  // session progress — every po_id ever seen in the queue, minus what's left
  const everSeen = useRef(new Set<number>());
  items.forEach((i) => everSeen.current.add(i.po_id));
  const cleared = useMemo(() => {
    const left = new Set(items.map((i) => i.po_id));
    return [...everSeen.current].filter((id) => !left.has(id)).length;
  }, [items]);

  const ext = useExtractionDecision(view.data);

  // advance once the current PO leaves the queue (resolved), or lands off-filter
  useEffect(() => {
    if (queue.isLoading || items.length === 0) return;
    const resolved = poId != null && !items.some((i) => i.po_id === poId);
    if (resolved || poId == null) {
      const next = (filtered[0] ?? items[0])?.po_id;
      if (next != null && next !== poId) nav(`/reconcile/${next}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poId, items, queue.isLoading]);

  useEffect(() => {
    if (filter === "all" || filtered.length === 0) return;
    if (poId == null || !filtered.some((i) => i.po_id === poId)) {
      nav(`/reconcile/${filtered[0].po_id}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const go = (delta: number) => {
    if (!filtered.length) return;
    const at = idx < 0 ? 0 : Math.min(Math.max(idx + delta, 0), filtered.length - 1);
    nav(`/reconcile/${filtered[at].po_id}`);
  };
  const bestInvoice = () => view.data?.candidates[0]?.invoice_id ?? null;

  useHotkeys([
    ["j", () => go(1)],
    ["k", () => go(-1)],
    ["ArrowRight", () => go(1)],
    ["ArrowLeft", () => go(-1)],
    ["s", () => go(1)],
    ["e", () => poId != null && nav(`/po/${poId}`)],
    ["mod+k", () => jump.open()],
    ["1", () => canEdit && ext.pick("is_po" as Verdict)],
    ["2", () => canEdit && ext.pick("not_po" as Verdict)],
    ["3", () => canEdit && ext.pick("needs_fix" as Verdict)],
    ["4", () => canEdit && ext.pick("revision" as Verdict)],
    ["y", () => {
      const inv = bestInvoice();
      if (canEdit && inv != null && poId != null) confirm.mutate({ po_id: poId, invoice_id: inv });
    }],
    ["n", () => {
      const inv = bestInvoice();
      if (canEdit && inv != null && poId != null) reject.mutate({ po_id: poId, invoice_id: inv });
    }],
  ]);

  return (
    <PageLayout title={meta.title} description={meta.description} breadcrumbs={meta.breadcrumbs} width="wide">
      <Box maw={940} mx="auto">
        <Stack gap="md">
          <ReviewHeader
            position={idx >= 0 ? idx + 1 : 0}
            total={filtered.length}
            cleared={cleared}
            filter={filter}
            onFilter={setFilter}
            counts={queue.data?.counts ?? { extraction: 0, match: 0 }}
            onPrev={() => go(-1)}
            onNext={() => go(1)}
            onSkip={() => go(1)}
            onJump={jump.open}
            canPrev={idx > 0}
            canNext={idx >= 0 && idx < filtered.length - 1}
          />

          {queue.isLoading ? (
            <Loader m="xl" />
          ) : queue.error ? (
            <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
          ) : items.length === 0 ? (
            <Text c="dimmed" p="xl" ta="center">
              Nothing needs reconciling. 🎉
            </Text>
          ) : poId == null ? (
            <Text c="dimmed" p="xl" ta="center">
              Loading the first order…
            </Text>
          ) : view.isLoading ? (
            <Loader m="xl" />
          ) : view.error ? (
            <ErrorState error={view.error} onRetry={() => void view.refetch()} />
          ) : view.data ? (
            <ReviewStream view={view.data} ext={ext} />
          ) : null}
        </Stack>
      </Box>

      <QueueJump
        opened={jumpOpen}
        onClose={jump.close}
        items={items}
        selected={poId}
        onSelect={(id) => nav(`/reconcile/${id}`)}
      />
    </PageLayout>
  );
}
