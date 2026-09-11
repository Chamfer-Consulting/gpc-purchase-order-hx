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
}

export interface YieldEntry {
  id: number;
  yield_product_id: number;
  product_name: string;
  harvest_date: string;
  weight: number;
  unit: YieldUnit;
  tray_count: number;
  discarded_tray_count: number;
  storage_bin: string | null;
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
}

export interface YieldEntryIn {
  yield_product_id: number;
  harvest_date: string;
  weight: number;
  unit: YieldUnit;
  tray_count: number;
  discarded_tray_count: number;
  storage_bin?: string | null;
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

export function useCreateYieldProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; notes?: string | null }) =>
      apiSend<YieldProduct>("POST", "/api/yields/products", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-products"] }),
  });
}

export function useUpdateYieldProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; active?: boolean; notes?: string | null }) =>
      apiSend<YieldProduct>("POST", `/api/yields/products/${id}`, body),
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
    mutationFn: (body: { yield_product_id: number; sales_product_name: string }) =>
      apiSend<YieldLink>("POST", "/api/yields/links", body),
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

export function useYieldEntries(filters: YieldEntryFilters = {}) {
  return useQuery({
    queryKey: ["yield-entries", filters],
    queryFn: () => apiGet<YieldEntry[]>("/api/yields/entries", { ...filters }),
    staleTime: 15_000,
  });
}

export function useCreateYieldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: YieldEntryIn) => apiSend<YieldEntry>("POST", "/api/yields/entries", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yield-entries"] }),
  });
}

export function useVoidYieldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string | null }) =>
      apiSend<YieldEntry>("POST", `/api/yields/entries/${id}/void`, { reason }),
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
