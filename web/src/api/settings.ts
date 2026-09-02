import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export type VisibilityDim = "products" | "customers";

export interface VisibilityRow {
  name: string;
  n_lines: number;
  hidden: boolean;
}

const visKey = (dim: VisibilityDim) => ["visibility", dim] as const;

export function useVisibility(dim: VisibilityDim) {
  return useQuery({
    queryKey: visKey(dim),
    queryFn: () => apiGet<VisibilityRow[]>(`/api/settings/hidden-${dim}`),
    staleTime: 5 * 60_000,
  });
}

export function useSetVisible(dim: VisibilityDim) {
  const qc = useQueryClient();
  const key = visKey(dim);
  return useMutation({
    mutationFn: (body: { name: string; hidden: boolean }) =>
      apiSend<{ ok: boolean }>("POST", `/api/settings/hidden-${dim}`, body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<VisibilityRow[]>(key);
      if (prev) {
        qc.setQueryData<VisibilityRow[]>(
          key,
          prev.map((r) => (r.name === body.name ? { ...r, hidden: body.hidden } : r)),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: key });
      // every analytics view + the filter dropdowns depend on the hidden sets
      for (const k of [
        "overview", "customers", "products", "explore", "explore-pivot",
        "explore-compare", "lifecycle", "data-quality", "pricing", "pricing-history",
        "filter-options",
      ]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    },
  });
}

export interface HiddenInvoice {
  qbo_invoice_id: string;
  reason: string | null;
  hidden_at: string | null;
  doc_number: string | null;
  customer_name: string | null;
  txn_date: string | null;
  total_amt: number | null;
}

/** The invoices a human excluded from every analytics page (phantom recurring
 *  auto-invoices). A review / restore list — not the full invoice history. */
export function useHiddenInvoices() {
  return useQuery({
    queryKey: ["hidden-invoices"],
    queryFn: () => apiGet<HiddenInvoice[]>("/api/settings/hidden-invoices"),
    staleTime: 60_000,
  });
}

export function useSetInvoiceHidden() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { qbo_invoice_id: string; hidden: boolean; reason?: string }) =>
      apiSend<{ ok: boolean }>("POST", "/api/settings/hidden-invoices", body),
    onSuccess: () => {
      for (const k of [
        "hidden-invoices", "overview", "customers", "products", "explore",
        "explore-pivot", "explore-compare", "lifecycle", "data-quality",
        "pricing", "pricing-history", "filter-options",
      ]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    },
  });
}

export interface SavedView<C = Record<string, unknown>> {
  name: string;
  config: C;
}

export function useSavedViews<C = Record<string, unknown>>(kind: string) {
  return useQuery({
    queryKey: ["saved-views", kind],
    queryFn: () => apiGet<SavedView<C>[]>("/api/settings/views", { kind }),
    staleTime: 5 * 60_000,
  });
}

export function useSaveView() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: string; name: string; config: Record<string, unknown> }) =>
      apiSend<{ ok: boolean }>("POST", "/api/settings/views", body),
    onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: ["saved-views", v.kind] }),
  });
}

export function useDeleteView(kind: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiSend<{ ok: boolean }>("DELETE", "/api/settings/views", { kind, name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-views", kind] }),
  });
}
