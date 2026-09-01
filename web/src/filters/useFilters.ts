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

// list filters ride the URL / API as repeated keys (?customers=a&customers=b), so a
// value that contains a comma — "Get Fresh Produce, Inc." — survives intact. (A
// pre-existing bookmark using the old ?customers=a,b joined form reads back as one
// literal chip "a,b"; re-pick to fix — rare and self-correcting.)
const readList = (sp: URLSearchParams, key: string): string[] =>
  sp.getAll(key).filter(Boolean);

export function useFilters(): {
  filters: Filters;
  setFilters: (patch: Partial<Filters>) => void;
  queryParams: Record<string, string | string[]>;
} {
  const [sp, setSp] = useSearchParams();

  const filters = useMemo<Filters>(
    () => ({
      start: sp.get("start"),
      end: sp.get("end"),
      customers: readList(sp, "customers"),
      products: readList(sp, "products"),
      sizes: readList(sp, "sizes"),
      includeSamples: sp.get("include_samples") === "1",
    }),
    [sp],
  );

  const setFilters = useCallback(
    (patch: Partial<Filters>) => {
      const next = new URLSearchParams(sp);
      const put = (k: string, v: string | null) => (v ? next.set(k, v) : next.delete(k));
      const putList = (k: string, arr: string[] | undefined) => {
        next.delete(k);
        for (const item of arr ?? []) if (item) next.append(k, item);
      };
      if ("start" in patch) put("start", patch.start ?? null);
      if ("end" in patch) put("end", patch.end ?? null);
      if ("customers" in patch) putList("customers", patch.customers);
      if ("products" in patch) putList("products", patch.products);
      if ("sizes" in patch) putList("sizes", patch.sizes);
      if ("includeSamples" in patch) put("include_samples", patch.includeSamples ? "1" : null);
      setSp(next, { replace: true });
    },
    [sp, setSp],
  );

  const queryParams = useMemo<Record<string, string | string[]>>(() => {
    const p: Record<string, string | string[]> = {};
    if (filters.start) p.start = filters.start;
    if (filters.end) p.end = filters.end;
    if (filters.customers.length) p.customers = filters.customers;
    if (filters.products.length) p.products = filters.products;
    if (filters.sizes.length) p.sizes = filters.sizes;
    if (filters.includeSamples) p.include_samples = "1";
    return p;
  }, [filters]);

  return { filters, setFilters, queryParams };
}
