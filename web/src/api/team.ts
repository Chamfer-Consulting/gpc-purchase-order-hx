import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";
import type { Role } from "./me";

export interface TeamMember {
  email: string;
  /** the explicit app_users grant, or null if none */
  role: Role | null;
  /** what they actually run as: role, else viewer if allowed, else null (blocked) */
  effective_role: Role | null;
  /** identity gate — false = signed up but the API rejects them */
  allowed: boolean;
  has_role: boolean;
  has_account: boolean;
  note: string | null;
  signed_up_at: string | null;
  last_sign_in_at: string | null;
}

/** The app_users allow / role list. Admin-only endpoint. */
export function useTeam(enabled = true) {
  return useQuery({
    queryKey: ["team"],
    queryFn: () => apiGet<TeamMember[]>("/api/settings/team"),
    enabled,
    staleTime: 60_000,
  });
}

export function useSetTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: Role; note?: string | null }) =>
      apiSend<{ ok: boolean }>("POST", "/api/settings/team", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["team"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useRemoveTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (email: string) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/settings/team/${encodeURIComponent(email)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["team"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
