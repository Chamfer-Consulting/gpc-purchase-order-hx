import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export interface FilterOptions {
  customers: string[];
  products: string[];
  sizes: string[];
}

/** Distinct values for the customer / product / size MultiSelects. Rarely
 * changes — cache hard. */
export function useFilterOptions() {
  return useQuery({
    queryKey: ["filter-options"],
    queryFn: () => apiGet<FilterOptions>("/api/filters/options"),
    staleTime: 10 * 60_000,
  });
}
