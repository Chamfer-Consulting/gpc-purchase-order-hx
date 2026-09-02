import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface ReferencePrice {
  id: number;
  customer_name: string;
  product_name: string;
  container_size: string;
  price: number;
  source: string; // "auto" | "manual"
  edited: boolean;
  edited_at: string | null;
  updated_at: string | null;
}

export interface PriceOption {
  product_name: string;
  container_size: string;
}

interface PricesResponse {
  reference_prices: ReferencePrice[];
  options: PriceOption[];
}

export interface PricePoint {
  date: string | null;
  customer_name: string | null;
  /** unit price exactly as recorded on the PO line */
  unit_price: number;
  /** unit price with the baked-in per-item delivery fee removed (== unit_price when
   *  the order already itemised delivery) */
  unit_price_adj: number;
  /** before / after the pricing-standardization band */
  era: "pre" | "post";
  delivery_itemised: boolean;
}

export interface PriceHistory {
  product_name: string;
  container_size: string;
  /** shaded transition to standardized pricing (inclusive YYYY-MM-DD bounds) */
  standardization_band: { start: string; end: string };
  points: PricePoint[];
  reference_prices: { customer_name: string; price: number; source: string }[];
  /** monthly median of the delivery-adjusted price from the band end onward */
  standardized_trend: { date: string; price: number }[];
}

export interface RefPriceRow {
  customer_name: string;
  product_name: string;
  container_size: string;
  price: number;
}

export function useReferencePrices() {
  return useQuery({
    queryKey: ["pricing"],
    queryFn: () => apiGet<PricesResponse>("/api/pricing"),
    staleTime: 2 * 60_000,
  });
}

export function usePriceHistory(product: string | null, size: string | null) {
  return useQuery({
    queryKey: ["pricing-history", product, size],
    queryFn: () =>
      apiGet<PriceHistory>("/api/pricing/history", { product: product!, size: size! }),
    enabled: Boolean(product && size),
    staleTime: 5 * 60_000,
  });
}

export function useSavePrices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { rows: RefPriceRow[]; delete: string[][] }) =>
      apiSend<{ ok: boolean; saved: number; deleted: number }>("POST", "/api/pricing", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pricing"] });
      qc.invalidateQueries({ queryKey: ["pricing-history"] });
    },
  });
}
