import { useEffect, useMemo, useState } from "react";
import { Autocomplete, Badge, Group, Stack, Text } from "@mantine/core";
import type { ReconcilePoView } from "@/api/reconcile";
import { usePoSearch } from "@/api/poEdit";
import { useUpsertDecision } from "@/api/review";
import { notifySuccess } from "@/lib/notify";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";

export type Verdict = "is_po" | "not_po" | "needs_fix" | "revision";

interface PoOpt {
  customer: string | null;
  date: string | null;
  total: number | null;
  sibling: boolean;
}

/** Autocomplete for "this thread revises PO …" — seeded with the detected sibling
 *  orders plus a live PO-number search. Free text still allowed. */
export function RevisionOfInput({
  view,
  value,
  onChange,
  disabled,
}: {
  view: ReconcilePoView;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const search = usePoSearch(value);

  const { data, meta } = useMemo(() => {
    const m = new Map<string, PoOpt>();
    for (const r of view.revisions ?? []) {
      if (r.po_number && r.po_id !== view.header.id && r.status === "active") {
        m.set(r.po_number, { customer: r.customer_name, date: r.po_date, total: r.total, sibling: true });
      }
    }
    for (const h of search.data ?? []) {
      if (h.po_number && h.po_id !== view.header.id && !m.has(h.po_number)) {
        m.set(h.po_number, { customer: h.customer_name, date: h.po_date, total: h.total, sibling: false });
      }
    }
    return { data: [...m.keys()].map((v) => ({ value: v })), meta: m };
  }, [view.revisions, view.header.id, search.data]);

  return (
    <Autocomplete
      size="xs"
      w={300}
      label="Revises PO / thread"
      placeholder="PO number, or gmail-thread:<id>"
      disabled={disabled}
      value={value}
      onChange={onChange}
      data={data}
      limit={20}
      comboboxProps={{ withinPortal: true }}
      renderOption={({ option }) => {
        const o = meta.get(option.value);
        return (
          <Stack gap={0} py={2}>
            <Group gap={6}>
              <Text size="sm" fw={500}>
                PO {option.value}
              </Text>
              {o?.sibling && (
                <Badge size="xs" variant="light" color="gpGreen">
                  likely
                </Badge>
              )}
            </Group>
            {o && (
              <Text size="xs" c="dimmed" style={NUMERIC_STYLE}>
                {o.customer ?? "—"}
                {o.date ? ` · ${o.date}` : ""}
                {o.total != null ? ` · ${fmtCurrency(o.total)}` : ""}
              </Text>
            )}
          </Stack>
        );
      }}
    />
  );
}

/** Verdict state + save-on-select for one PO's extraction decision. Safe to call
 *  before the view has loaded (no-ops until it has). */
export function useExtractionDecision(view: ReconcilePoView | undefined, onSaved?: () => void) {
  const ext = view?.extraction;
  const upsert = useUpsertDecision();

  const [verdict, setVerdict] = useState<Verdict>("is_po");
  const [revisionOf, setRevisionOf] = useState("");

  useEffect(() => {
    if (!ext) return;
    setVerdict(ext.revision_of ? "revision" : (ext.verdict ?? "is_po"));
    setRevisionOf(ext.revision_of ?? "");
  }, [ext?.verdict, ext?.revision_of, view?.header.id]);

  const save = (v: Verdict, revOf = revisionOf) => {
    if (!ext) return;
    upsert.mutate(
      {
        target_kind: ext.target_kind,
        target_key: ext.target_key,
        verdict: v === "revision" ? "is_po" : v,
        revision_of: v === "revision" ? revOf.trim() || null : null,
      },
      {
        onSuccess: () => {
          notifySuccess("Extraction decision saved.");
          onSaved?.();
        },
      },
    );
  };

  /** pick a verdict; everything but "revision" saves immediately */
  const pick = (v: Verdict) => {
    setVerdict(v);
    if (v !== "revision") save(v);
  };

  return { verdict, pick, setVerdict, revisionOf, setRevisionOf, save, saving: upsert.isPending };
}
