import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";
import type { PoDetail, PoLink } from "@/api/poEdit";

export type LineDiffStatus =
  | "match"
  | "qty_diff"
  | "price_diff"
  | "total_diff"
  | "po_only"
  | "inv_only";

export interface LineDiffSide {
  quantity: number | null;
  unit_price: number | null;
  line_total: number | null;
  product_name: string | null;
  container_size: string | null;
}

export interface LineDiffRow {
  product: string | null;
  size: string | null;
  po: LineDiffSide | null;
  inv: LineDiffSide | null;
  status: LineDiffStatus;
  deltas: { quantity: number | null; unit_price: number | null; line_total: number | null };
  /** the trailing row that reconciles PO freight vs the invoice's delivery lines */
  is_charges?: boolean;
}

export interface LineDiff {
  rows: LineDiffRow[];
  totals: { po: number; inv: number; delta: number };
  n_rows: number;
  n_diff: number;
  clean: boolean;
}

export interface ReconcileCandidate {
  po_id: number;
  invoice_id: number;
  match_method: string;
  match_score: number | null;
  po_number: string | null;
  po_customer: string | null;
  po_total: number | null;
  doc_number: string | null;
  inv_customer: string | null;
  txn_date: string | null;
  total_amt: number | null;
  confidence: string;
  quick: boolean;
  /** deep link into QuickBooks' own invoice view */
  qbo_url: string | null;
  /** the PO number recorded on the QBO invoice itself ("PO Number" custom field) */
  inv_po_number: string | null;
  /** invoice's PO number vs this order's, normalised — null if the invoice has none */
  po_number_match: boolean | null;
  diff: LineDiff;
  /** set when this invoice is already confirmed to a DIFFERENT PO — confirming here
   *  would violate one-invoice-one-PO and is rejected server-side; unlink there first */
  other_confirmed_po?: { po_id: number; po_number: string | null } | null;
}

export interface ReconcileExtraction {
  target_kind: "thread" | "file";
  target_key: string;
  snapshot: string | null;
  snapshot_hash: string | null;
  gmail_url: string | null;
  subject: string | null;
  verdict: "is_po" | "not_po" | "needs_fix" | null;
  revision_of: string | null;
  standalone: boolean;
  note: string | null;
  decided_at: string | null;
}

export interface ReconcilePoView extends PoDetail {
  extraction: ReconcileExtraction;
  candidates: ReconcileCandidate[];
  links: (PoLink & {
    diff?: LineDiff;
    inv_po_number?: string | null;
    po_number_match?: boolean | null;
  })[];
}

export type Stage = "extraction" | "lifecycle" | "match";

export interface QueueItem {
  po_id: number;
  reasons: string[];
  priority: number;
  stage: Stage;
  customer_name: string | null;
  po_number?: string | null;
  po_date?: string | null;
  subject?: string | null;
  total?: number | null;
  n_candidates?: number;
}

export interface ReconcileQueue {
  items: QueueItem[];
  counts: { extraction: number; match: number; total: number; unlinked_no_candidate: number };
}

export function useReconcileQueue() {
  return useQuery({
    queryKey: ["reconcile-queue"],
    queryFn: () => apiGet<ReconcileQueue>("/api/reconcile/queue"),
    staleTime: 30_000,
  });
}

export function useReconcilePo(poId: number | null) {
  return useQuery({
    queryKey: ["reconcile-po", poId],
    queryFn: () => apiGet<ReconcilePoView>(`/api/reconcile/po/${poId}`),
    enabled: poId != null && Number.isFinite(poId),
  });
}

/** Confirm / reject a match candidate, optimistically dropping it from the
 *  cached PO view; rolls back on error, refetches queue + view on settle. */
function useMatchDecision(action: "confirm" | "reject") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: { po_id: number; invoice_id: number }) =>
      apiSend<{ ok: boolean }>("POST", `/api/matching/${action}`, ref),
    onMutate: async (ref) => {
      const key = ["reconcile-po", ref.po_id];
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<ReconcilePoView>(key);
      if (prev) {
        qc.setQueryData<ReconcilePoView>(key, {
          ...prev,
          candidates: prev.candidates.filter((c) => c.invoice_id !== ref.invoice_id),
        });
      }
      return { prev, key };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(ctx.key, ctx.prev);
    },
    onSettled: (_d, _e, ref) => {
      qc.invalidateQueries({ queryKey: ["reconcile-po", ref.po_id] });
      qc.invalidateQueries({ queryKey: ["reconcile-queue"] });
      qc.invalidateQueries({ queryKey: ["po", ref.po_id] });
    },
  });
}

export const useReconcileConfirm = () => useMatchDecision("confirm");
export const useReconcileReject = () => useMatchDecision("reject");

export function useConfirmBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pairs: { po_id: number; invoice_id: number }[]) =>
      apiSend<{ ok: boolean; confirmed: unknown[] }>("POST", "/api/matching/confirm-batch", {
        pairs,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reconcile-queue"] });
      qc.invalidateQueries({ queryKey: ["reconcile-po"] });
    },
  });
}
