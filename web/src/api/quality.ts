import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { PageResponse } from "./schema";

export function useDataQuality() {
  return useQuery({
    queryKey: ["data-quality"],
    queryFn: () => apiGet<PageResponse>("/api/data-quality"),
  });
}
