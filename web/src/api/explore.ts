import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useFilters } from "@/filters/useFilters";
import type { PageResponse } from "./schema";

export type Measure = "revenue" | "orders" | "quantity";
export type Grain = "day" | "week" | "month" | "quarter" | "year" | "all";
export type Dim = "customer" | "product" | "size";

export interface PivotConfig {
  measure: Measure;
  grain: Grain;
  dims: Dim[];
}

export function usePivot(cfg: PivotConfig) {
  const { queryParams } = useFilters();
  const params = {
    ...queryParams,
    measure: cfg.measure,
    grain: cfg.grain,
    dims: cfg.dims.join(","),
  };
  return useQuery({
    queryKey: ["explore-pivot", params],
    queryFn: () => apiGet<PageResponse>("/api/explore/pivot", params),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

export interface ComparePeriods {
  a_start: string;
  a_end: string;
  b_start: string;
  b_end: string;
}

export function useCompare(ranges: ComparePeriods | null) {
  const { queryParams } = useFilters();
  const params = ranges ? { ...queryParams, ...ranges } : {};
  return useQuery({
    queryKey: ["explore-compare", params],
    queryFn: () => apiGet<PageResponse>("/api/explore/compare", params),
    enabled: Boolean(ranges),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}
