import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { YieldGrain } from "@/api/yields";

/** URL-held scope for the Yields Trends page — date range, grain, and which
 *  products. Deliberately separate from web/src/filters/useFilters.ts (the PO
 *  domain's customers/products/sizes scope) rather than shoehorned into it —
 *  "product" here means yield_product_id, a different universe, and grain has
 *  no PO-domain equivalent. */
export interface YieldFilters {
  dateFrom: string | null;
  dateTo: string | null;
  productIds: number[];
  grain: YieldGrain;
}

const GRAINS: YieldGrain[] = ["week", "month", "quarter", "year"];

export function useYieldFilters(): {
  filters: YieldFilters;
  setFilters: (patch: Partial<YieldFilters>) => void;
} {
  const [sp, setSp] = useSearchParams();

  const filters = useMemo<YieldFilters>(() => {
    const g = sp.get("grain");
    return {
      dateFrom: sp.get("date_from"),
      dateTo: sp.get("date_to"),
      productIds: sp.getAll("product_id").map(Number).filter((n) => !Number.isNaN(n)),
      grain: (GRAINS as string[]).includes(g ?? "") ? (g as YieldGrain) : "month",
    };
  }, [sp]);

  const setFilters = useCallback(
    (patch: Partial<YieldFilters>) => {
      const next = new URLSearchParams(sp);
      if ("dateFrom" in patch) {
        if (patch.dateFrom) next.set("date_from", patch.dateFrom);
        else next.delete("date_from");
      }
      if ("dateTo" in patch) {
        if (patch.dateTo) next.set("date_to", patch.dateTo);
        else next.delete("date_to");
      }
      if ("productIds" in patch) {
        next.delete("product_id");
        for (const id of patch.productIds ?? []) next.append("product_id", String(id));
      }
      if ("grain" in patch) {
        if (patch.grain) next.set("grain", patch.grain);
        else next.delete("grain");
      }
      setSp(next, { replace: true });
    },
    [sp, setSp],
  );

  return { filters, setFilters };
}
