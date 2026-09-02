import { useEffect, useRef, useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Text } from "@mantine/core";
import { usePo, useSavePo, type PoHeader, type PoLineItem } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { notifySuccess } from "@/lib/notify";
import { EMPTY_LINE, PoLineItemsEditor, type EditableLine } from "./PoLineItemsEditor";

/** Edit one PO's line items in a modal — the fast path from a Data Quality row
 *  (math check / price anomaly / no-size) so a person can correct the flagged
 *  line without leaving the queue. Saves through the same POST /api/po/:id the
 *  Edit PO page uses, so math / price flags recompute and the row drops off. */
export function PoFixModal({ poId, onClose }: { poId: number | null; onClose: () => void }) {
  return (
    <Modal
      opened={poId != null}
      onClose={onClose}
      size="xl"
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

  useEffect(() => {
    if (!data) return;
    setItems(data.items.map((it) => makeRow(it)));
    setHeader(data.header);
    setSaveErr(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

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
        expected_version: data!.header.lock_version,
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
