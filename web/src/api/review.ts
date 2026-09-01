import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface QueueItem {
  po_id: number;
  target_kind: "thread" | "file";
  target_key: string;
  reason: string;
  priority: number;
  customer_name: string | null;
  po_date: string | null;
  n_items: number;
  error: string | null;
  subject: string | null;
  from_addrs: string | null;
  gmail_url: string | null;
  snapshot: string | null;
  decided: boolean;
  stale: boolean;
}

export interface RevisionCandidate {
  a_po_id: number;
  b_po_id: number;
  customer_name: string;
  delivery_date: string | null;
  a_po_number: string | null;
  b_po_number: string | null;
  a_group_key: string;
  b_kind: "thread" | "file";
  b_key: string;
}

export interface DecisionRow {
  target_kind: string;
  target_key: string;
  verdict: string;
  revision_of: string | null;
  standalone: boolean;
  note: string | null;
  reviewer: string | null;
  updated_at: string | null;
}

export interface DecisionInput {
  target_kind: string;
  target_key: string;
  verdict: "is_po" | "not_po" | "needs_fix";
  revision_of?: string | null;
  standalone?: boolean;
  corrected?: Record<string, unknown> | null;
  note?: string | null;
}

export const useReviewQueue = () =>
  useQuery({ queryKey: ["review-queue"], queryFn: () => apiGet<{ items: QueueItem[] }>("/api/review/queue") });

export const useRevisionCandidates = () =>
  useQuery({
    queryKey: ["review-candidates"],
    queryFn: () => apiGet<{ items: RevisionCandidate[] }>("/api/review/candidates"),
  });

export const useDecisions = () =>
  useQuery({ queryKey: ["review-decisions"], queryFn: () => apiGet<{ items: DecisionRow[] }>("/api/review/decisions") });

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  [
    "review-queue",
    "review-candidates",
    "review-decisions",
    "data-quality",
    // the /reconcile screen reads these — a decision resolves a queue item
    "reconcile-queue",
    "reconcile-po",
  ].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

export function useUpsertDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (d: DecisionInput) => apiSend<{ ok: boolean }>("POST", "/api/review/decision", d),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useDeleteDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (t: { target_kind: string; target_key: string }) =>
      apiSend<{ ok: boolean }>("DELETE", "/api/review/decision", t),
    onSuccess: () => invalidateAll(qc),
  });
}

export interface BulkStatusResult {
  ok: boolean;
  status: string;
  updated: number[];
  failed: { po_id: number; error: string }[];
}

/** Set one lifecycle status on many POs at once (triage from the review queue). */
export function useBulkStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { po_ids: number[]; status: string; reason?: string | null }) =>
      apiSend<BulkStatusResult>("POST", "/api/bulk/po-status", body),
    onSuccess: () => {
      invalidateAll(qc);
      qc.invalidateQueries({ queryKey: ["archive"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}
