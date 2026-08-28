import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useFilters } from "@/filters/useFilters";
import type { PageResponse } from "./schema";

export type PageName = "overview" | "customers" | "products" | "explore" | "lifecycle";

/** One analytics page's data, scoped by the current URL filters. */
export function usePage(name: PageName) {
  const { queryParams } = useFilters();
  return useQuery({
    queryKey: [name, queryParams],
    queryFn: () => apiGet<PageResponse>(`/api/${name}`, queryParams),
  });
}
