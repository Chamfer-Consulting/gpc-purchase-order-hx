import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface PoLineItem {
  id?: number;
  product_raw?: string | null;
  product_name?: string | null;
  container_size?: string | null;
  quantity?: number | null;
  unit_price?: number | null;
  line_total?: number | null;
  additional_cost?: number | null;
  sku?: string | null;
  is_sample?: boolean;
  math_mismatch?: string | null;
  price_anomaly?: string | null;
  revision_status?: string | null;
}

export interface PoHeader {
  id: number;
  source_file: string;
  po_number: string | null;
  po_date: string | null;
  delivery_date: string | null;
  customer_name: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  notes: string | null;
  edited: boolean;
}

export interface PoDetail {
  header: PoHeader;
  items: PoLineItem[];
  removed_items: PoLineItem[];
}

export function usePo(poId: number) {
  return useQuery({
    queryKey: ["po", poId],
    queryFn: () => apiGet<PoDetail>(`/api/po/${poId}`),
    enabled: Number.isFinite(poId),
  });
}

export function useSavePo(poId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      header: Partial<PoHeader>;
      items: PoLineItem[];
      removed_items: PoLineItem[];
    }) => apiSend<{ ok: boolean; math_check_failed: boolean; math_check_detail: string }>(
      "POST",
      `/api/po/${poId}`,
      body,
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["po", poId] });
      qc.invalidateQueries({ queryKey: ["data-quality"] });
    },
  });
}
