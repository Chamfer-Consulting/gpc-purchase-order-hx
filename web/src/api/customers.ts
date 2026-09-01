import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useFilters } from "@/filters/useFilters";
import type { PageResponse } from "./schema";

/** One account's dossier — revenue, cadence, product & size mix — scoped by the
 *  FilterBar's date range. The customer is the route, not a filter. */
export function useCustomerDetail(name: string | undefined) {
  const { queryParams } = useFilters();
  return useQuery({
    queryKey: ["customer-detail", name, queryParams],
    queryFn: () =>
      apiGet<PageResponse>(`/api/customers/${encodeURIComponent(name!)}`, queryParams),
    enabled: !!name,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}
