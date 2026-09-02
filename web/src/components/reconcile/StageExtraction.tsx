import { useEffect, useMemo, useState } from "react";
import {
  Anchor,
  Autocomplete,
  Badge,
  Code,
  Group,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
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
 *  orders, plus a live PO-number search. Free text still allowed. */
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
        m.set(r.po_number, {
          customer: r.customer_name,
          date: r.po_date,
          total: r.total,
          sibling: true,
        });
      }
    }
    for (const h of search.data ?? []) {
      if (h.po_number && h.po_id !== view.header.id && !m.has(h.po_number)) {
        m.set(h.po_number, {
          customer: h.customer_name,
          date: h.po_date,
          total: h.total,
          sibling: false,
        });
      }
    }
    return { data: [...m.keys()].map((v) => ({ value: v })), meta: m };
  }, [view.revisions, view.header.id, search.data]);

  return (
    <Autocomplete
      size="xs"
      w={280}
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

/** Verdict state + save for one PO's extraction decision. The DecisionBar owns
 *  the controls; this holds the wiring. */
export function useExtractionDecision(view: ReconcilePoView) {
  const ext = view.extraction;
  const upsert = useUpsertDecision();

  const initial: Verdict = ext.revision_of ? "revision" : (ext.verdict ?? "is_po");
  const [verdict, setVerdict] = useState<Verdict>(initial);
  const [revisionOf, setRevisionOf] = useState(ext.revision_of ?? "");

  useEffect(() => {
    setVerdict(ext.revision_of ? "revision" : (ext.verdict ?? "is_po"));
    setRevisionOf(ext.revision_of ?? "");
  }, [ext.verdict, ext.revision_of, view.header.id]);

  const save = (v: Verdict = verdict, revOf = revisionOf) =>
    upsert.mutate(
      {
        target_kind: ext.target_kind,
        target_key: ext.target_key,
        verdict: v === "revision" ? "is_po" : v,
        revision_of: v === "revision" ? revOf.trim() || null : null,
      },
      { onSuccess: () => notifySuccess("Extraction decision saved.") },
    );

  return { verdict, setVerdict, revisionOf, setRevisionOf, save, saving: upsert.isPending };
}

/** The evidence: what we pulled off the email vs what got extracted. */
export function ExtractionBody({ view }: { view: ReconcilePoView }) {
  const ext = view.extraction;
  const items = view.items;

  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
      <Stack gap={6}>
        <Group gap="xs">
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            Source
          </Text>
          {ext.gmail_url && (
            <Anchor href={ext.gmail_url} target="_blank" rel="noreferrer" size="xs">
              <Group gap={3}>
                Open Gmail thread <IconExternalLink size={11} />
              </Group>
            </Anchor>
          )}
        </Group>
        {ext.subject && (
          <Text size="sm" fw={500}>
            {ext.subject}
          </Text>
        )}
        {ext.snapshot ? (
          <ScrollArea.Autosize mah={460}>
            <Code block fz={11}>
              {ext.snapshot}
            </Code>
          </ScrollArea.Autosize>
        ) : (
          <Text size="sm" c="dimmed">
            No stored extraction snapshot for this order.
          </Text>
        )}
      </Stack>

      <Stack gap={6}>
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Extracted
        </Text>
        <Text size="sm">
          {view.header.customer_name ?? "no customer"} · {view.header.po_date ?? "no date"} ·{" "}
          {fmtCurrency(view.header.total)}
        </Text>
        <Table fz="xs" verticalSpacing={3} withRowBorders>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Product</Table.Th>
              <Table.Th ta="right">Qty</Table.Th>
              <Table.Th ta="right">Total</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((it, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  {it.product_name ?? it.product_raw ?? "?"}
                  {it.container_size ? ` · ${it.container_size}` : ""}
                </Table.Td>
                <Table.Td ta="right" style={NUMERIC_STYLE}>
                  {it.quantity ?? "—"}
                </Table.Td>
                <Table.Td ta="right" style={NUMERIC_STYLE}>
                  {fmtCurrency(it.line_total, true)}
                </Table.Td>
              </Table.Tr>
            ))}
            {items.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text size="xs" c="dimmed">
                    No line items extracted.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Stack>
    </SimpleGrid>
  );
}
