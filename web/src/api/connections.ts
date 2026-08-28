import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface ConnectionsStatus {
  gmail: { email_address: string; connected_at: string | null; last_synced_at: string | null } | null;
  qbo: {
    realm_id: string;
    connected_at: string | null;
    last_synced_at: string | null;
    refresh_token_expires_at: string | null;
    auto_synced_at: string | null;
    auto_sync_error: string | null;
    environment: string;
  } | null;
}

export function useConnections() {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => apiGet<ConnectionsStatus>("/api/connections"),
    staleTime: 15_000,
  });
}

/** Fetches the provider's authorize URL and sends the browser there. */
export function useConnect(provider: "gmail" | "qbo") {
  return useMutation({
    mutationFn: async () => {
      const { url } = await apiGet<{ url: string }>(`/api/connections/${provider}/authorize`);
      window.location.href = url;
    },
  });
}

export function useDisconnect(provider: "gmail" | "qbo") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<{ ok: boolean }>("POST", `/api/connections/${provider}/disconnect`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
  });
}

export function useQboSyncNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fullResync: boolean) =>
      apiSend<{ items: number; synced: number; deleted: number }>(
        "POST",
        `/api/connections/qbo/sync${fullResync ? "?full_resync=true" : ""}`,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
  });
}
