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
import { usePoEditForm } from "@/hooks/usePoEditForm";
import { useUnsavedGuard } from "@/hooks/useUnsavedGuard";
import { useRealtimeInvalidate } from "@/lib/realtime";
import { confirmAction } from "@/lib/modals";
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

  // The line-item editor embedded in OrderSource — lifted up here (not owned by
  // OrderSource itself) so keyboard/queue navigation can check `form.isDirty`
  // before sweeping an in-progress edit away, and the browser tab-close guard
  // covers it too. `poId ?? -1` is a harmless placeholder id while nothing is
  // selected yet — `view.data` is undefined then anyway (useReconcilePo only
  // enables once poId is set), so the form just stays clean.
  const form = usePoEditForm(poId ?? -1, view.data);
  useUnsavedGuard(form.isDirty);

  /** Everywhere this page moves off the current PO (hotkeys, prev/next, queue
   *  jump, "open full editor") funnels through here — a dirty line-item edit
   *  gets a chance to be kept before it's silently discarded by navigating away.
   *  Unlike EditPoPage (where losing dirty <Link> navigation is an accepted gap
   *  — see useUnsavedGuard), Reconcile's whole point is rapid keyboard-driven
   *  movement between orders, so an unguarded "j" mid-edit is a real footgun. */
  function guardedNav(go_: () => void) {
    if (!form.isDirty) {
      go_();
      return;
    }
    confirmAction({
      title: "Discard unsaved changes?",
      body: "This order's line items were edited but not saved. Leaving now discards the edit.",
      confirmLabel: "Discard & continue",
      onConfirm: go_,
    });
  }

  // advance once the current PO leaves the queue (resolved), or lands off-filter.
  // Never auto-advance out from under a dirty edit — it'll fire again once the
  // form clears (save or discard). A po_id that was never IN `items` to begin
  // with (a direct link — e.g. Data Quality's "Fix" action landing on a PO whose
  // only open issue is a data-quality one, not an extraction/match one) is NOT
  // "resolved": `everSeen` only ever gains ids that were actually queue items,
  // so this correctly leaves a deep-linked PO alone instead of bouncing to
  // whatever's first in the queue.
  useEffect(() => {
    if (queue.isLoading || items.length === 0 || form.isDirty) return;
    const resolved = poId != null && everSeen.current.has(poId) && !items.some((i) => i.po_id === poId);
    if (resolved || poId == null) {
      const next = (filtered[0] ?? items[0])?.po_id;
      if (next != null && next !== poId) nav(`/reconcile/${next}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poId, items, queue.isLoading, form.isDirty]);

  useEffect(() => {
    if (filter === "all" || filtered.length === 0) return;
    if (poId == null || !filtered.some((i) => i.po_id === poId)) {
      nav(`/reconcile/${filtered[0].po_id}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const go = (delta: number) =>
    guardedNav(() => {
      if (!filtered.length) return;
      const at = idx < 0 ? 0 : Math.min(Math.max(idx + delta, 0), filtered.length - 1);
      nav(`/reconcile/${filtered[at].po_id}`);
    });
  const bestInvoice = () => view.data?.candidates[0]?.invoice_id ?? null;

  useHotkeys([
    ["j", () => go(1)],
    ["k", () => go(-1)],
    ["ArrowRight", () => go(1)],
    ["ArrowLeft", () => go(-1)],
    ["s", () => go(1)],
    ["e", () => poId != null && guardedNav(() => nav(`/po/${poId}`))],
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
    <PageLayout title={meta.title} description={meta.description} breadcrumbs={meta.breadcrumbs} width="full">
      <Box>
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
          ) : poId != null ? (
            // A specific PO is selected — show it regardless of whether the queue
            // itself is empty. A direct link (e.g. Data Quality's "Fix" action) can
            // land on a PO whose only open issue isn't an extraction/match one, so
            // it's never IN `items` at all; "Nothing needs reconciling" below is
            // only for the bare /reconcile landing with no PO picked.
            view.isLoading ? (
              <Loader m="xl" />
            ) : view.error ? (
              <ErrorState error={view.error} onRetry={() => void view.refetch()} />
            ) : view.data ? (
              <ReviewStream view={view.data} ext={ext} form={form} />
            ) : null
          ) : items.length === 0 ? (
            <Text c="dimmed" p="xl" ta="center">
              Nothing needs reconciling. 🎉
            </Text>
          ) : (
            <Text c="dimmed" p="xl" ta="center">
              Loading the first order…
            </Text>
          )}
        </Stack>
      </Box>

      <QueueJump
        opened={jumpOpen}
        onClose={jump.close}
        items={items}
        selected={poId}
        onSelect={(id) => guardedNav(() => nav(`/reconcile/${id}`))}
      />
    </PageLayout>
  );
}
