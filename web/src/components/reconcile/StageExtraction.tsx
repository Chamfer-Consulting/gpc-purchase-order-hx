import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Anchor,
  Autocomplete,
  Badge,
  Button,
  Code,
  Group,
  ScrollArea,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
import type { ReconcilePoView } from "@/api/reconcile";
import { usePoSearch } from "@/api/poEdit";
import { useUpsertDecision } from "@/api/review";
import { useMe } from "@/api/me";
import { notifySuccess } from "@/lib/notify";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { SectionCard } from "@/components/SectionCard";

type Verdict = "is_po" | "not_po" | "needs_fix" | "revision";

interface PoOpt {
  customer: string | null;
  date: string | null;
  total: number | null;
  sibling: boolean;
}

/** Autocomplete for "this thread revises PO …" — seeded with the detected
 *  sibling orders, plus a live PO-number search. Free text still allowed
 *  (e.g. gmail-thread:<id>). */
function RevisionOfInput({
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

export function StageExtraction({ view }: { view: ReconcilePoView }) {
  const { canEdit, roleKnown } = useMe();
  const ext = view.extraction;
  const upsert = useUpsertDecision();

  const initial: Verdict = ext.revision_of ? "revision" : (ext.verdict ?? "is_po");
  const [verdict, setVerdict] = useState<Verdict>(initial);
  const [revisionOf, setRevisionOf] = useState(ext.revision_of ?? "");

  useEffect(() => {
    setVerdict(ext.revision_of ? "revision" : (ext.verdict ?? "is_po"));
    setRevisionOf(ext.revision_of ?? "");
  }, [ext.verdict, ext.revision_of, view.header.id]);

  function save(v: Verdict, revOf = revisionOf) {
    upsert.mutate(
      {
        target_kind: ext.target_kind,
        target_key: ext.target_key,
        verdict: v === "revision" ? "is_po" : v,
        revision_of: v === "revision" ? revOf.trim() || null : null,
      },
      { onSuccess: () => notifySuccess("Extraction decision saved.") },
    );
  }

  const items = view.items;

  return (
    <SectionCard
      title="1 · Extraction"
      subtitle="Is what we pulled off the email actually this order?"
      actions={
        ext.verdict && (
          <Badge variant="light" color={ext.verdict === "not_po" ? "red" : "gpGreen"}>
            decided: {ext.verdict}
            {ext.decided_at ? ` · ${ext.decided_at.slice(0, 10)}` : ""}
          </Badge>
        )
      }
    >
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
            <ScrollArea.Autosize mah={420}>
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

      <Group align="flex-end" gap="sm" wrap="wrap">
        <div>
          <Text size="xs" fw={600} c="dimmed" mb={4}>
            Verdict
          </Text>
          <SegmentedControl
            size="xs"
            value={verdict}
            onChange={(v) => setVerdict(v as Verdict)}
            disabled={!canEdit}
            data={[
              { value: "is_po", label: "Looks right" },
              { value: "not_po", label: "Not a PO" },
              { value: "needs_fix", label: "Needs fix" },
              { value: "revision", label: "Revision of…" },
            ]}
          />
        </div>
        {verdict === "revision" && (
          <RevisionOfInput
            view={view}
            value={revisionOf}
            onChange={setRevisionOf}
            disabled={!canEdit}
          />
        )}
        <Button size="xs" onClick={() => save(verdict)} loading={upsert.isPending} disabled={!canEdit}>
          Save decision
        </Button>
        {verdict === "needs_fix" && (
          <Button
            size="xs"
            variant="light"
            component={Link}
            to={`/po/${view.header.id}`}
          >
            Open full editor
          </Button>
        )}
      </Group>
      {roleKnown && !canEdit && (
        <Text size="xs" c="dimmed">
          Recording a decision needs the editor role.
        </Text>
      )}
    </SectionCard>
  );
}
