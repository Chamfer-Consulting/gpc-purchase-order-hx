import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface MatchCandidate {
  po_id: number;
  invoice_id: number;
  match_method: string;
  match_score: number | null;
  po_number: string | null;
  po_customer: string | null;
  po_total: number | null;
  po_date: string | null;
  delivery_date: string | null;
  doc_number: string | null;
  inv_customer: string | null;
  txn_date: string | null;
  total_amt: number | null;
}
export interface LineItem {
  product_name: string | null;
  container_size: string | null;
  quantity: number | null;
  unit_price: number | null;
  line_total: number | null;
  is_sample?: boolean;
}
export interface MatchReview {
  candidates: MatchCandidate[];
  po_items: Record<string, LineItem[]>;
  inv_items: Record<string, LineItem[]>;
  unlinked: { po_id: number; po_number: string | null; customer_name: string | null }[];
}

export function useMatchReview() {
  return useQuery({ queryKey: ["match-review"], queryFn: () => apiGet<MatchReview>("/api/matching/review") });
}

export function useRunMatching() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<Record<string, number>>("POST", "/api/matching/run"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["match-review"] }),
  });
}

function useLinkAction(action: "confirm" | "reject") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: { po_id: number; invoice_id: number }) =>
      apiSend<{ ok: boolean }>("POST", `/api/matching/${action}`, ref),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["match-review"] }),
  });
}
export const useConfirmLink = () => useLinkAction("confirm");
export const useRejectLink = () => useLinkAction("reject");

/** Manual PO↔invoice link for an arbitrary pair (the admin workbench). */
export function useManualLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: { po_id: number; invoice_id: number; replace_existing?: boolean }) =>
      apiSend<{ ok: boolean }>("POST", "/api/links", {
        replace_existing: false,
        ...ref,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["match-review"] });
      qc.invalidateQueries({ queryKey: ["po"] });
    },
  });
}
