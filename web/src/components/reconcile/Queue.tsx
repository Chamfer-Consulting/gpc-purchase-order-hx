import { Badge, Box, Group, ScrollArea, Stack, Text } from "@mantine/core";
import { IconClipboardCheck, IconArrowsShuffle } from "@tabler/icons-react";
import type { QueueItem, Stage } from "@/api/reconcile";
import classes from "./Queue.module.css";

const STAGE_META: Record<Stage, { label: string; color: string; Icon: typeof IconClipboardCheck }> = {
  extraction: { label: "Extraction", color: "gpGold", Icon: IconClipboardCheck },
  lifecycle: { label: "Lifecycle", color: "blue", Icon: IconClipboardCheck },
  match: { label: "Match", color: "gpGreen", Icon: IconArrowsShuffle },
};

export function Queue({
  items,
  selected,
  onSelect,
}: {
  items: QueueItem[];
  selected: number | null;
  onSelect: (poId: number) => void;
}) {
  return (
    <ScrollArea.Autosize mah="calc(100vh - 220px)" type="hover">
      <Stack gap={4} pr="xs">
        {items.map((it) => {
          const { label, color, Icon } = STAGE_META[it.stage];
          const active = it.po_id === selected;
          return (
            <Box
              key={it.po_id}
              role="button"
              tabIndex={0}
              className={`${classes.row} ${active ? classes.active : ""}`}
              onClick={() => onSelect(it.po_id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(it.po_id)}
            >
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text size="sm" fw={600} truncate>
                  {it.po_number ?? `PO ${it.po_id}`}
                </Text>
                <Badge size="xs" variant="light" color={color} leftSection={<Icon size={10} />}>
                  {label}
                </Badge>
              </Group>
              <Text size="xs" c="dimmed" truncate>
                {it.customer_name ?? "—"}
                {it.po_date ? ` · ${it.po_date.slice(0, 10)}` : ""}
              </Text>
              <Text size="xs" c="dimmed" lineClamp={2}>
                {it.reasons.join(" · ")}
              </Text>
            </Box>
          );
        })}
        {items.length === 0 && (
          <Text size="sm" c="dimmed" p="md" ta="center">
            Nothing needs reconciling. 🎉
          </Text>
        )}
      </Stack>
    </ScrollArea.Autosize>
  );
}
