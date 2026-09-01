import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";
import type { Role } from "./me";

export interface TeamMember {
  email: string;
  role: Role;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
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
