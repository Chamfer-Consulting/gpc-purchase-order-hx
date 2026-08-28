import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { supabase } from "./supabase";

/**
 * Invalidate the given TanStack Query keys whenever a row in `table` changes.
 * Uses Supabase Realtime (Postgres CDC) — the table must be in the
 * `supabase_realtime` publication (see docs/REBUILD-SETUP.md §6). No-ops quietly
 * if Realtime isn't enabled.
 */
export function useRealtimeInvalidate(table: string, queryKeys: string[]) {
  const qc = useQueryClient();
  useEffect(() => {
    const channel = supabase
      .channel(`rt:${table}`)
      .on("postgres_changes", { event: "*", schema: "public", table }, () => {
        for (const key of queryKeys) qc.invalidateQueries({ queryKey: [key] });
      })
      .subscribe();
    return () => {
      void supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table]);
}
