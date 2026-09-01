import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useFilters } from "@/filters/useFilters";
import type { PageResponse } from "./schema";

/** Data Quality fix queue. Extraction failures are all-time; math / price /
 *  questionable-match / invoice-recon tables follow the current FilterBar scope. */
export function useDataQuality() {
  const { queryParams } = useFilters();
  return useQuery({
    queryKey: ["data-quality", queryParams],
    queryFn: () => apiGet<PageResponse>("/api/data-quality", queryParams),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
