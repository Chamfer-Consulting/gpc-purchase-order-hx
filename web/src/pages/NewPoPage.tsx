import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Group, Stack, Textarea } from "@mantine/core";
import { useCreatePo, type PoHeader, type PoLineItem } from "@/api/poEdit";
import { useMe } from "@/api/me";
import { notifySuccess } from "@/lib/notify";
import { fieldErrors } from "@/lib/errors";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { PoHeaderFields, headerErrors } from "@/components/po/PoHeaderFields";
import {
  EMPTY_LINE,
  PoLineItemsEditor,
  sumLineTotals,
  type EditableLine,
} from "@/components/po/PoLineItemsEditor";

export function NewPoPage() {
  const nav = useNavigate();
  const create = useCreatePo();
  const { canEdit, roleKnown } = useMe();

  const [header, setHeader] = useState<Partial<PoHeader>>({});
  const [items, setItems] = useState<EditableLine[]>([]);
  const rk = useRef(0);
  const makeRow = (seed?: Partial<PoLineItem>): EditableLine => ({
    ...EMPTY_LINE,
    ...seed,
    _rk: `r${rk.current++}`,
  });

  const errors = useMemo(
    () => ({ ...headerErrors(header, { requireIdentity: true }), ...fieldErrors(create.error) }),
    [header, create.error],
  );
  const hasErrors = Object.keys(errors).length > 0;

  return (
    <PageLayout
      title="New purchase order"
      description="A PO typed in by hand (phone order, walk-in). It is created active and marked edited, so the extraction pipeline never touches it."
      breadcrumbs={[{ label: "Reconcile", to: "/reconcile" }, { label: "New PO" }]}
      width="form"
      actions={
        <Button variant="subtle" onClick={() => nav(-1)}>
          Cancel
        </Button>
      }
    >
      <Stack gap="lg">
        <SectionCard title="Order details">
          <PoHeaderFields value={header} onChange={(p) => setHeader((h) => ({ ...h, ...p }))} errors={errors} disabled={!canEdit} />
        </SectionCard>

        <SectionCard title="Line items">
          <PoLineItemsEditor
            items={items}
            onChange={setItems}
            makeRow={makeRow}
            headerTotal={header.total ?? null}
            disabled={!canEdit}
          />
          <Textarea
            label="Notes"
            value={header.notes ?? ""}
            onChange={(e) => setHeader((h) => ({ ...h, notes: e.currentTarget.value }))}
            autosize
            minRows={2}
          />

          {roleKnown && !canEdit && (
            <Alert color="gray" variant="light" title="View-only access">
              Creating a purchase order needs the editor role.
            </Alert>
          )}
          {create.error && !fieldErrors(create.error).po_number && (
            <Alert color="red">{(create.error as Error).message}</Alert>
          )}

          <Group>
            <Button
              loading={create.isPending}
              disabled={!canEdit || hasErrors}
              onClick={() =>
                create.mutate(
                  { header: { ...header, subtotal: header.subtotal ?? null }, items },
                  {
                    onSuccess: (r) => {
                      notifySuccess("Purchase order created.");
                      nav(`/po/${r.po_id}`);
                    },
                  },
                )
              }
            >
              Create PO
            </Button>
            {items.length > 0 && (
              <span style={{ fontSize: 12, color: "var(--mantine-color-dimmed)" }}>
                {items.length} line{items.length === 1 ? "" : "s"} · Σ{" "}
                {sumLineTotals(items).toFixed(2)}
              </span>
            )}
          </Group>
        </SectionCard>
      </Stack>
    </PageLayout>
  );
}
