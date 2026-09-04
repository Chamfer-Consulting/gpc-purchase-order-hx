import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Text } from "@mantine/core";
import { usePo, useSavePo, type PoDetail, type PoHeader, type PoLineItem } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { useIsMobile } from "@/hooks/useIsMobile";
import { notifySuccess } from "@/lib/notify";
import { EMPTY_LINE, PoLineItemsEditor, type EditableLine } from "./PoLineItemsEditor";

const HEADER_KEYS: (keyof PoHeader)[] = [
  "po_number", "customer_name", "po_date", "delivery_date", "subtotal", "tax", "total", "notes",
];
const ITEM_KEYS: (keyof PoLineItem)[] = [
  "id", "product_name", "container_size", "quantity", "unit_price", "line_total",
  "additional_cost", "voided",
];

/** Compare the editable slice of the form to the server copy — same shape as
 *  EditPoPage's formEqual, so both editors agree on what counts as "unsaved". */
function formEqual(header: Partial<PoHeader>, items: EditableLine[], data: PoDetail): boolean {
  for (const k of HEADER_KEYS) if ((header[k] ?? null) !== (data.header[k] ?? null)) return false;
  if (items.length !== data.items.length) return false;
  for (let i = 0; i < items.length; i++) {
    for (const k of ITEM_KEYS) if ((items[i][k] ?? null) !== (data.items[i][k] ?? null)) return false;
  }
  return true;
}

/** Edit one PO's line items in a modal — the fast path from a Data Quality row
 *  (math check / price anomaly / no-size) so a person can correct the flagged
 *  line without leaving the queue. Saves through the same POST /api/po/:id the
 *  Edit PO page uses, so math / price flags recompute and the row drops off. */
export function PoFixModal({ poId, onClose }: { poId: number | null; onClose: () => void }) {
  const isMobile = useIsMobile();
  return (
    <Modal
      opened={poId != null}
      onClose={onClose}
      size="xl"
      fullScreen={isMobile}
      title={poId != null ? `Fix PO ${poId}` : "Fix"}
    >
      {poId != null && <Body poId={poId} onClose={onClose} />}
    </Modal>
  );
}

function Body({ poId, onClose }: { poId: number; onClose: () => void }) {
  const { data, isLoading, error } = usePo(poId);
  const save = useSavePo(poId);
  const { canEdit } = useMe();

  const rk = useRef(0);
  const makeRow = (seed?: Partial<PoLineItem>): EditableLine => ({
    ...EMPTY_LINE,
    ...seed,
    _rk: `r${rk.current++}`,
  });

  const [items, setItems] = useState<EditableLine[]>([]);
  const [header, setHeader] = useState<Partial<PoHeader>>({});
  const [saveErr, setSaveErr] = useState<string | null>(null);
  // Seeded once per PO open, not on every background refetch of `data` — otherwise
  // a query invalidation while the person is mid-edit (another tab, a realtime
  // update elsewhere on the page) silently wipes what they just typed. Mirrors
  // EditPoPage's dirty-guarded reseed.
  const seededRef = useRef<number | null>(null);
  // The lock_version the form was actually built from — sent as expected_version so
  // a save still 409s correctly if the PO changed on the server while dirty (the
  // dirty-guarded reseed above means `data.header.lock_version` itself can already
  // have moved past what's on screen).
  const [seededVersion, setSeededVersion] = useState<number | undefined>(undefined);
  const isDirty = useMemo(
    () => (data && seededRef.current === poId ? !formEqual(header, items, data) : false),
    [header, items, data, poId],
  );
  const dirtyRef = useRef(false);
  dirtyRef.current = isDirty;

  useEffect(() => {
    if (!data) return;
    if (seededRef.current === poId && dirtyRef.current) return;
    setItems(data.items.map((it) => makeRow(it)));
    setHeader(data.header);
    setSaveErr(null);
    seededRef.current = poId;
    setSeededVersion(data.header.lock_version);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, poId]);

  if (isLoading) return <Loader size="sm" />;
  if (error)
    return (
      <Text c="red" size="sm">
        {(error as Error).message}
      </Text>
    );
  if (!data) return null;

  function doSave() {
    setSaveErr(null);
    const clean: PoLineItem[] = items.map(({ _rk: _drop, ...r }) => r);
    save.mutate(
      {
        header,
        items: clean,
        removed_items: data!.removed_items,
        expected_version: seededVersion ?? data!.header.lock_version,
      },
      {
        onSuccess: () => {
          notifySuccess("Saved — the queue refreshes.");
          onClose();
        },
        onError: (e) => setSaveErr((e as Error).message),
      },
    );
  }

  return (
    <Stack gap="md">
      {!canEdit && (
        <Alert color="gray" variant="light" title="View only">
          You can review this order's lines but not change them.
        </Alert>
      )}

      <PoLineItemsEditor
        items={items}
        onChange={setItems}
        makeRow={makeRow}
        headerTotal={data.header.total}
        disabled={!canEdit || save.isPending}
      />

      {saveErr && (
        <Text c="red" size="sm">
          {saveErr}
        </Text>
      )}

      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={doSave} loading={save.isPending} disabled={!canEdit}>
          Save
        </Button>
      </Group>
    </Stack>
  );
}
