import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useFilters } from "@/filters/useFilters";
import type { PageResponse } from "./schema";

export type PageName = "overview" | "customers" | "products" | "explore" | "lifecycle";

/** One analytics page's data, scoped by the current URL filters. The backend
 * memoises these for ~5 min, so match that here and keep the previous payload
 * on screen while a new scope loads (no loading flash on a filter change). */
export function usePage(name: PageName) {
  const { queryParams } = useFilters();
  return useQuery({
    queryKey: [name, queryParams],
    queryFn: () => apiGet<PageResponse>(`/api/${name}`, queryParams),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}
