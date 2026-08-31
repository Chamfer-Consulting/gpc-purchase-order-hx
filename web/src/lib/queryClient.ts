import { MutationCache, QueryClient } from "@tanstack/react-query";
import { notifyError } from "./notify";

/**
 * Any mutation that fails shows an error toast, unless it opts out with
 * `meta: { silent: true }` (e.g. a page that renders the error inline / maps it
 * to field errors, or a 409 the page handles with a conflict banner).
 */
export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (err, _vars, _ctx, mutation) => {
      if (mutation.meta?.silent) return;
      notifyError(err);
    },
  }),
  defaultOptions: {
    queries: {
      // Analytics data changes on a sync cadence, not per-second — lean on the cache.
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
