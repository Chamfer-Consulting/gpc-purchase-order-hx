import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";

export type Role = "field" | "external_viewer" | "viewer" | "editor" | "admin";

export interface Me {
  email: string | null;
  role: Role;
  /** Admin-granted nav pages (web/src/nav.tsx `to` paths) — only ever
   *  non-empty for role === "external_viewer". */
  external_pages: string[];
}

/** field / external_viewer < viewer < editor < admin. 'field' is the Product
 *  Yields kiosk role; 'external_viewer' is an admin-toggled, page-by-page
 *  outside account — both sit below 'viewer', more restricted than an
 *  ungranted signed-in user, never the loading-state fallback below.
 *  'external_viewer' isn't really a rung on this ladder (see auth.py's
 *  require_page) but still needs a rank for canEdit/canAdmin comparisons. */
const RANK: Record<Role, number> = { field: 0, external_viewer: 0, viewer: 1, editor: 2, admin: 3 };

/** Current user + app role. Cached long — role changes are rare and the backend
 *  caches too. `role` falls back to `viewer` while loading/erroring, but
 *  AccountGate blocks rendering of anything that reads it (RoleRouter
 *  included) until the query actually succeeds — this fallback is never
 *  observed past that gate. */
export function useMe() {
  const { session } = useAuth();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/api/me"),
    enabled: !!session,
    staleTime: 5 * 60_000,
  });
  const role: Role = q.data?.role ?? "viewer";
  return {
    ...q,
    role,
    email: q.data?.email ?? session?.user.email ?? null,
    externalPages: q.data?.external_pages ?? [],
    canEdit: RANK[role] >= RANK.editor,
    canAdmin: RANK[role] >= RANK.admin,
    /** true only once we actually know the role (avoid a flash of disabled UI) */
    roleKnown: q.isSuccess,
  };
}
