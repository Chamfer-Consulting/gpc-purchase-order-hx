import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

/** One event in the cross-system activity feed. `source` says where it came from:
 *  "admin" = an admin mutation (audit_log), "review" = an extraction-review decision. */
export interface AuditRow {
  source: "admin" | "review";
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
  limit?: number;
  offset?: number;
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

export function useAuditLog(filters: AuditFilters) {
  return useQuery({
    queryKey: ["audit", filters],
    queryFn: () => apiGet<AuditPage>("/api/audit", filters as Record<string, unknown>),
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
