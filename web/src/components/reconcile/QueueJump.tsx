import { useEffect, useMemo, useState } from "react";
import { Badge, Group, Modal, ScrollArea, Stack, Text, TextInput, UnstyledButton } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import type { QueueItem } from "@/api/reconcile";
import { fmtCurrency } from "@/lib/format";

const STAGE_LABEL: Record<string, string> = { extraction: "verdict", match: "match" };

/** ⌘K overlay — jump to any order in the queue. Replaces the two-column rail. */
export function QueueJump({
  opened,
  onClose,
  items,
  selected,
  onSelect,
}: {
  opened: boolean;
  onClose: () => void;
  items: QueueItem[];
  selected: number | null;
  onSelect: (poId: number) => void;
}) {
  const [q, setQ] = useState("");
  useEffect(() => {
    if (opened) setQ("");
  }, [opened]);

  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    if (!n) return items;
    return items.filter(
      (it) =>
        (it.po_number ?? String(it.po_id)).toLowerCase().includes(n) ||
        (it.customer_name ?? "").toLowerCase().includes(n) ||
        it.reasons.some((r) => r.toLowerCase().includes(n)),
    );
  }, [items, q]);

  const pick = (poId: number) => {
    onSelect(poId);
    onClose();
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Jump to an order" size="lg">
      <TextInput
        data-autofocus
        mb="sm"
        placeholder="PO number, customer, reason…"
        leftSection={<IconSearch size={14} />}
        value={q}
        onChange={(e) => setQ(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && shown.length) pick(shown[0].po_id);
        }}
      />
      <ScrollArea.Autosize mah={440}>
        <Stack gap={4}>
          {shown.map((it) => (
            <UnstyledButton
              key={it.po_id}
              onClick={() => pick(it.po_id)}
              px="sm"
              py={6}
              style={{
                borderRadius: "var(--mantine-radius-sm)",
                border: "1px solid var(--mantine-color-default-border)",
                background:
                  it.po_id === selected ? "var(--mantine-color-gpGreen-light)" : "var(--gp-surface)",
              }}
            >
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                  <Text size="sm" fw={600}>
                    {it.po_number ?? `PO ${it.po_id}`}
                  </Text>
                  <Text size="sm" c="dimmed" truncate>
                    {it.customer_name ?? "—"}
                  </Text>
                </Group>
                <Group gap={6} wrap="nowrap" style={{ flex: "none" }}>
                  {it.total != null && (
                    <Text size="xs" c="dimmed">
                      {fmtCurrency(it.total)}
                    </Text>
                  )}
                  <Badge size="xs" variant="light" color={it.stage === "match" ? "gpGreen" : "gpGold"}>
                    {STAGE_LABEL[it.stage] ?? it.stage}
                  </Badge>
                </Group>
              </Group>
              {it.reasons.length > 0 && (
                <Text size="xs" c="dimmed" truncate>
                  {it.reasons.join(" · ")}
                </Text>
              )}
            </UnstyledButton>
          ))}
          {shown.length === 0 && (
            <Text size="sm" c="dimmed" ta="center" py="md">
              No matching orders.
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>
    </Modal>
  );
}
