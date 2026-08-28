import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The dashboard's scope, held in the URL query string so every view is a
 * shareable link (the counterpart to dashboard/filters.py). Every analytics
 * endpoint takes these as params.
 */
export interface Filters {
  start: string | null;
  end: string | null;
  customers: string[];
  products: string[];
  sizes: string[];
  includeSamples: boolean;
}

const LIST = (v: string | null): string[] => (v ? v.split(",").filter(Boolean) : []);

export function useFilters(): {
  filters: Filters;
  setFilters: (patch: Partial<Filters>) => void;
  queryParams: Record<string, string>;
} {
  const [sp, setSp] = useSearchParams();

  const filters = useMemo<Filters>(
    () => ({
      start: sp.get("start"),
      end: sp.get("end"),
      customers: LIST(sp.get("customers")),
      products: LIST(sp.get("products")),
      sizes: LIST(sp.get("sizes")),
      includeSamples: sp.get("include_samples") === "1",
    }),
    [sp],
  );

  const setFilters = useCallback(
    (patch: Partial<Filters>) => {
      const next = new URLSearchParams(sp);
      const put = (k: string, v: string | null) => (v ? next.set(k, v) : next.delete(k));
      if ("start" in patch) put("start", patch.start ?? null);
      if ("end" in patch) put("end", patch.end ?? null);
      if ("customers" in patch) put("customers", (patch.customers ?? []).join(","));
      if ("products" in patch) put("products", (patch.products ?? []).join(","));
      if ("sizes" in patch) put("sizes", (patch.sizes ?? []).join(","));
      if ("includeSamples" in patch) put("include_samples", patch.includeSamples ? "1" : null);
      setSp(next, { replace: true });
    },
    [sp, setSp],
  );

  const queryParams = useMemo<Record<string, string>>(() => {
    const p: Record<string, string> = {};
    if (filters.start) p.start = filters.start;
    if (filters.end) p.end = filters.end;
    if (filters.customers.length) p.customers = filters.customers.join(",");
    if (filters.products.length) p.products = filters.products.join(",");
    if (filters.sizes.length) p.sizes = filters.sizes.join(",");
    if (filters.includeSamples) p.include_samples = "1";
    return p;
  }, [filters]);

  return { filters, setFilters, queryParams };
}
