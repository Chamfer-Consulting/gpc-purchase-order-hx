import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";

export type Role = "field" | "viewer" | "editor" | "admin";

export interface Me {
  email: string | null;
  role: Role;
}

/** field < viewer < editor < admin. 'field' is the Product Yields kiosk role —
 *  more restricted than viewer, never the loading-state fallback below. */
const RANK: Record<Role, number> = { field: 0, viewer: 1, editor: 2, admin: 3 };

/** Current user + app role. Cached long — role changes are rare and the backend
 *  caches too. Falls back to `viewer` (least privilege) until it loads. */
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
    canEdit: RANK[role] >= RANK.editor,
    canAdmin: RANK[role] >= RANK.admin,
    /** true only once we actually know the role (avoid a flash of disabled UI) */
    roleKnown: q.isSuccess,
  };
}
