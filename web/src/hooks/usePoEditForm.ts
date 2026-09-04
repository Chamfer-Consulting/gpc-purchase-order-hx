import { useEffect, useMemo, useRef, useState } from "react";
import type { PoDetail, PoHeader, PoLineItem } from "@/api/poEdit";
import { EMPTY_LINE, type EditableLine } from "@/components/po/PoLineItemsEditor";

const HEADER_KEYS: (keyof PoHeader)[] = [
  "po_number", "customer_name", "po_date", "delivery_date", "subtotal", "tax", "total", "notes",
];
const ITEM_KEYS: (keyof PoLineItem)[] = [
  "id", "product_name", "container_size", "quantity", "unit_price", "line_total",
  "additional_cost", "voided",
];

/** Compare the editable slice of the form to the server copy. */
function formEqual(header: Partial<PoHeader>, items: EditableLine[], data: PoDetail): boolean {
  for (const k of HEADER_KEYS) if ((header[k] ?? null) !== (data.header[k] ?? null)) return false;
  if (items.length !== data.items.length) return false;
  for (let i = 0; i < items.length; i++) {
    for (const k of ITEM_KEYS) if ((items[i][k] ?? null) !== (data.items[i][k] ?? null)) return false;
  }
  return true;
}

/**
 * Shared editable-PO form state: header fields + line items, seeded from the
 * server payload, dirty-guarded against background refetches (a query
 * invalidation mid-edit — another tab, a realtime update, a sibling mutation on
 * the same page — must never silently wipe what's on screen), with the seeded
 * lock_version tracked separately from the live one so a save's
 * optimistic-concurrency check stays honest even though a dirty form
 * deliberately doesn't reseed when the server moves ahead of it.
 *
 * One implementation, not three — EditPoPage, the Reconcile inline editor, and
 * (previously) the standalone Data Quality fix modal all edit the exact same
 * shape of data the exact same way; a bug fixed here (or a rule changed here)
 * no longer needs finding and re-fixing in each copy.
 */
export function usePoEditForm(poId: number, data: PoDetail | undefined, onSeed?: (d: PoDetail) => void) {
  const rk = useRef(0);
  const makeRow = (seed?: Partial<PoLineItem>): EditableLine => ({
    ...EMPTY_LINE,
    ...seed,
    _rk: `r${rk.current++}`,
  });

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  const [items, setItems] = useState<EditableLine[]>([]);
  // Which PO's data is currently loaded into the form — until the first payload
  // for a given poId lands, an empty/stale form must NOT read as a dirty edit.
  const seededRef = useRef<number | null>(null);
  const [seededVersion, setSeededVersion] = useState<number | undefined>(undefined);

  const isDirty = useMemo(
    () => (data && seededRef.current === poId ? !formEqual(header, items, data) : false),
    [header, items, data, poId],
  );
  const dirtyRef = useRef(false);
  dirtyRef.current = isDirty;

  function reseed(d: PoDetail) {
    setHeader(d.header);
    setItems(d.items.map((it) => makeRow(it)));
    seededRef.current = poId;
    setSeededVersion(d.header.lock_version);
    onSeed?.(d);
  }

  useEffect(() => {
    if (!data) return;
    // Seed on first load / when the route switched to a different PO; on a
    // background refetch of the SAME PO, only take the server copy if the form
    // is clean (a void / status / link mutation elsewhere on the page must not
    // wipe in-progress edits).
    if (seededRef.current !== data.header.id || !dirtyRef.current) reseed(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, poId]);

  const serverMovedAhead =
    isDirty && seededVersion != null && data != null && data.header.lock_version !== seededVersion;

  return { header, setHeader, items, setItems, makeRow, isDirty, seededVersion, serverMovedAhead, reseed };
}
