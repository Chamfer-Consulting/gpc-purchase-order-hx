import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

/** rows fetched per page / per "Load more" */
export const AUDIT_PAGE = 50;

/** One event in the cross-system activity feed. `source` says where it came from:
 *  "admin" = an admin mutation (audit_log), "auth" = a sign-in / sign-out,
 *  "review" = an extraction-review decision. */
export interface AuditRow {
  source: "admin" | "auth" | "review";
  id: string;
  at: string | null;
  actor: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  /** the "why" — derived from the before/after slice, or null if none was given */
  reason: string | null;
  before: unknown;
  after: unknown;
}

export interface AuditFilters {
  actor?: string;
  source?: string;
  action?: string;
  entity?: string;
  q?: string;
  /** inclusive YYYY-MM-DD bounds */
  since?: string;
  until?: string;
}

export interface AuditPage {
  rows: AuditRow[];
  has_more: boolean;
}

export interface AuditOptions {
  actors: string[];
  actions: string[];
  entities: string[];
  sources: string[];
}

/** Paginated feed: each page is AUDIT_PAGE rows at a growing offset; `fetchNextPage`
 *  pulls the next slice while keeping the ones already shown. Changing `filters`
 *  starts a fresh query at offset 0. */
export function useAuditLog(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: ["audit", filters],
    queryFn: ({ pageParam }) =>
      apiGet<AuditPage>("/api/audit", {
        ...filters,
        limit: AUDIT_PAGE,
        offset: pageParam,
      } as Record<string, unknown>),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.length * AUDIT_PAGE : undefined,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useAuditOptions() {
  return useQuery({
    queryKey: ["audit", "options"],
    queryFn: () => apiGet<AuditOptions>("/api/audit/options"),
    staleTime: 5 * 60_000,
  });
}
