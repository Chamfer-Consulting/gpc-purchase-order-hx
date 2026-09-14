import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";
import type { PageResponse } from "@/api/schema";

export type YieldUnit = "oz" | "lb" | "g";
export type YieldGrain = "week" | "month" | "quarter" | "year";

export interface YieldProduct {
  id: number;
  name: string;
  active: boolean;
  notes: string | null;
  /** Short lot-code prefix (e.g. "TK") — the entry form auto-fills the lot
   *  code field with this for traceability, without retyping it every time. */
  lot_code_prefix: string | null;
  /** Computed, not a DB column — true if any of this product's entries has
   *  its own free-text notes, or shares a lot_code with a yield_notes
   *  grower observation. Not related to `notes` above (a catalog
   *  description field on the product itself). */
  has_notes: boolean;
}

export interface YieldEntry {
  id: number;
  yield_product_id: number;
  product_name: string;
  /** The product's lot-code prefix (e.g. "TK") — only populated on list
   *  results (joined), not on the row returned from create/update/void. */
  product_lot_code_prefix: string | null;
  harvest_date: string;
  weight: number;
  unit: YieldUnit;
  tray_count: number;
  discarded_tray_count: number;
  lot_code: string | null;
  harvested_by: string;
  submitted_by: string;
  notes: string | null;
  voided: boolean;
  void_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface YieldEntryFilters {
  yield_product_id?: number;
  date_from?: string;
  date_to?: string;
  harvested_by?: string;
  submitted_by?: string;
  include_voided?: boolean;
  /** Only entries with a non-empty own `notes` field — for the Notes
   *  page's merged feed. */
  has_notes?: boolean;
}

export interface YieldEntryIn {
  yield_product_id: number;
  harvest_date: string;
  weight: number;
  unit: YieldUnit;
  tray_count: number;
  discarded_tray_count: number;
  lot_code?: string | null;
  harvested_by: string;
  notes?: string | null;
}

export function useYieldProducts(includeInactive = false) {
  return useQuery({
    queryKey: ["yield-products", includeInactive],
    queryFn: () => apiGet<YieldProduct[]>("/api/yields/products", { include_inactive: includeInactive }),
    staleTime: 60_000,
  });
}

// create/update's RETURNING clause is yield_products alone — has_notes is
// computed only by list_products' two-query join, so it's never on these.
type YieldProductMutationResult = Omit<YieldProduct, "has_notes">;

export function useCreateYieldProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; notes?: string | null; lot_code_prefix?: string | null }) =>
      apiSend<YieldProductMutationResult>("POST", "/api/yields/products", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-products"] }),
  });
}

export function useUpdateYieldProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number;
      name?: string;
      active?: boolean;
      notes?: string | null;
      lot_code_prefix?: string | null;
    }) => apiSend<YieldProductMutationResult>("POST", `/api/yields/products/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-products"] }),
  });
}

/** Only succeeds while the product has no harvest entries yet (backend 409s
 *  with code "in_use" otherwise) — retire it via useUpdateYieldProduct instead. */
export function useDeleteYieldProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiSend<{ ok: boolean }>("DELETE", `/api/yields/products/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-products"] }),
  });
}

export interface YieldLink {
  id: number;
  yield_product_id: number;
  product_name: string;
  sales_product_name: string;
}

export function useYieldLinks(yieldProductId?: number) {
  return useQuery({
    queryKey: ["yield-links", yieldProductId],
    queryFn: () =>
      apiGet<YieldLink[]>("/api/yields/links", yieldProductId ? { yield_product_id: yieldProductId } : undefined),
    staleTime: 30_000,
  });
}

export function useYieldSalesProductNames() {
  return useQuery({
    queryKey: ["yield-sales-product-names"],
    queryFn: () => apiGet<string[]>("/api/yields/sales-product-names"),
    staleTime: 60_000,
  });
}

export function useCreateYieldLink() {
  const qc = useQueryClient();
  return useMutation({
    // The create endpoint's RETURNING clause has no product_name (that's a
    // join only list_links does) — Omit it rather than claiming YieldLink's
    // full shape for a response that doesn't have it.
    mutationFn: (body: { yield_product_id: number; sales_product_name: string }) =>
      apiSend<Omit<YieldLink, "product_name">>("POST", "/api/yields/links", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-links"] }),
  });
}

export function useDeleteYieldLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiSend<{ ok: boolean }>("DELETE", `/api/yields/links/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-links"] }),
  });
}

export function useYieldEntries(filters: YieldEntryFilters = {}, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["yield-entries", filters],
    queryFn: () => apiGet<YieldEntry[]>("/api/yields/entries", { ...filters }),
    staleTime: 15_000,
    enabled: options?.enabled,
  });
}

// The backend's RETURNING clause for create/update/void is `yield_entries`
// alone (no join to yield_products), so these three never carry
// product_name/product_lot_code_prefix — only list_entries's joined rows do.
type YieldEntryMutationResult = Omit<YieldEntry, "product_name" | "product_lot_code_prefix">;

export function useCreateYieldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: YieldEntryIn) =>
      apiSend<YieldEntryMutationResult>("POST", "/api/yields/entries", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-entries"] }),
  });
}

export interface YieldEntryImportRow {
  yield_product_id: number;
  harvest_date: string;
  weight: number;
  unit: YieldUnit;
  tray_count?: number;
  lot_code?: string | null;
  harvested_by: string;
}

/** Admin-only, one-transaction bulk insert for historical data (the CSV
 *  import page) — tray_count is optional per row (defaults to 0; most
 *  historical records don't carry it), discarded_tray_count/notes are
 *  never set, and a single audit_log row summarizes the whole batch. The
 *  backend skips (doesn't create) any row that already matches a non-voided
 *  entry for the same product + date + weight + unit (also + lot_code when
 *  the row has one) — reported back as skipped_duplicates, so re-importing
 *  the template's own example rows, or the same file twice, doesn't double
 *  up, while two different entries that happen to share a lot code (e.g.
 *  two people harvesting into the same labeled bin) still both get created. */
export function useImportYieldEntries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entries: YieldEntryImportRow[]) =>
      apiSend<{ ok: boolean; created: number; skipped_duplicates: number }>(
        "POST",
        "/api/yields/entries/import",
        { entries },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-entries"] }),
  });
}

export interface YieldEntryPatch {
  harvest_date?: string;
  weight?: number;
  unit?: YieldUnit;
  tray_count?: number;
  discarded_tray_count?: number;
  lot_code?: string | null;
  harvested_by?: string;
  notes?: string | null;
}

/** Corrections to an already-logged entry. Backend enforces: a 'field'-rank
 *  caller may only touch its own same-day entries; every other role
 *  (viewer+) is unrestricted — see services/yields.py's _assert_can_touch. */
export function useUpdateYieldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: YieldEntryPatch & { id: number }) =>
      apiSend<YieldEntryMutationResult>("POST", `/api/yields/entries/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-entries"] }),
  });
}

export function useVoidYieldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string | null }) =>
      apiSend<YieldEntryMutationResult>("POST", `/api/yields/entries/${id}/void`, { reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-entries"] }),
  });
}

export interface YieldTrendsFilters {
  date_from?: string;
  date_to?: string;
  yield_product_id?: number[];
  grain?: YieldGrain;
}

export function useYieldTrends(filters: YieldTrendsFilters) {
  return useQuery({
    queryKey: ["yield-trends", filters],
    queryFn: () => apiGet<PageResponse>("/api/yields/trends", { ...filters }),
    staleTime: 30_000,
  });
}

export interface YieldNote {
  id: number;
  /** The lot it's about (the default/primary case), or null for a general
   *  note not specific to any one lot. */
  lot_code: string | null;
  note_date: string;
  note: string;
  submitted_by: string;
  created_at: string;
}

/** Admin-only for now, both here and on the backend (require_admin) — see
 *  routers/yields.py's notes section. */
export function useYieldNotes(lotCode?: string) {
  return useQuery({
    queryKey: ["yield-notes", lotCode],
    queryFn: () => apiGet<YieldNote[]>("/api/yields/notes", lotCode ? { lot_code: lotCode } : undefined),
    staleTime: 30_000,
  });
}

export function useCreateYieldNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { lot_code?: string | null; note: string; note_date?: string | null }) =>
      apiSend<YieldNote>("POST", "/api/yields/notes", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-notes"] }),
  });
}

export function useDeleteYieldNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiSend<{ ok: boolean }>("DELETE", `/api/yields/notes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-notes"] }),
  });
}

export interface YieldEmployee {
  id: number;
  name: string;
  active: boolean;
}

/** The kiosk's "harvested by" roster — a curated suggestion list, not a FK:
 *  yield_entries.harvested_by stays free text either way. */
export function useYieldEmployees(includeInactive = false) {
  return useQuery({
    queryKey: ["yield-employees", includeInactive],
    queryFn: () => apiGet<YieldEmployee[]>("/api/yields/employees", { include_inactive: includeInactive }),
    staleTime: 60_000,
  });
}

export function useCreateYieldEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string }) => apiSend<YieldEmployee>("POST", "/api/yields/employees", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-employees"] }),
  });
}

export function useUpdateYieldEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; active?: boolean }) =>
      apiSend<YieldEmployee>("POST", `/api/yields/employees/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-employees"] }),
  });
}

export function useDeleteYieldEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiSend<{ ok: boolean }>("DELETE", `/api/yields/employees/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-employees"] }),
  });
}
