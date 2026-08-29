import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface ProductVisibility {
  product_name: string;
  n_lines: number;
  hidden: boolean;
}

export function useHiddenProducts() {
  return useQuery({
    queryKey: ["hidden-products"],
    queryFn: () => apiGet<ProductVisibility[]>("/api/settings/hidden-products"),
    staleTime: 5 * 60_000,
  });
}

export function useSetHidden() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { product_name: string; hidden: boolean }) =>
      apiSend<{ ok: boolean }>("POST", "/api/settings/hidden-products", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["hidden-products"] }),
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
      apiSend<{ ok: boolean }>("DELETE", "/api/settings/views", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-views", kind] }),
  });
}
