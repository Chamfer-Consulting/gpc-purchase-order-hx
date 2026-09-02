import { Badge, Box, Collapse, Group, ScrollArea, Stack, Text, UnstyledButton } from "@mantine/core";
import { IconChevronDown } from "@tabler/icons-react";
import { useDisclosure } from "@mantine/hooks";
import type { QueueItem, ReconcileQueue, Stage } from "@/api/reconcile";
import { fmtCurrency } from "@/lib/format";
import classes from "./Queue.module.css";

const GROUPS: { stage: Stage; label: string }[] = [
  { stage: "extraction", label: "Needs a verdict" },
  { stage: "match", label: "Needs a match" },
];

function Row({
  it,
  active,
  onSelect,
}: {
  it: QueueItem;
  active: boolean;
  onSelect: (poId: number) => void;
}) {
  return (
    <Box
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
        {it.total != null && (
          <Text size="xs" c="dimmed" style={{ flex: "none" }}>
            {fmtCurrency(it.total)}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed" truncate>
        {it.customer_name ?? "—"}
        {it.po_date ? ` · ${it.po_date.slice(0, 10)}` : ""}
      </Text>
      {it.reasons.length > 0 && (
        <Group gap={4} mt={3} wrap="wrap">
          {it.reasons.slice(0, 2).map((r, i) => (
            <Badge key={i} size="xs" variant="dot" color="gray" style={{ textTransform: "none" }}>
              {r}
            </Badge>
          ))}
          {it.reasons.length > 2 && (
            <Text size="xs" c="dimmed">
              +{it.reasons.length - 2}
            </Text>
          )}
        </Group>
      )}
    </Box>
  );
}

function Section({
  label,
  rows,
  selected,
  onSelect,
}: {
  label: string;
  rows: QueueItem[];
  selected: number | null;
  onSelect: (poId: number) => void;
}) {
  const [open, { toggle }] = useDisclosure(true);
  if (rows.length === 0) return null;
  return (
    <div>
      <UnstyledButton onClick={toggle} w="100%" px={6} py={4}>
        <Group gap={6} wrap="nowrap">
          <IconChevronDown
            size={13}
            style={{ transform: open ? undefined : "rotate(-90deg)", transition: "transform 120ms" }}
          />
          <Text size="xs" fw={700}>
            {label}
          </Text>
          <Badge size="xs" variant="light" color="gray">
            {rows.length}
          </Badge>
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Stack gap={4} mt={2}>
          {rows.map((it) => (
            <Row key={it.po_id} it={it} active={it.po_id === selected} onSelect={onSelect} />
          ))}
        </Stack>
      </Collapse>
    </div>
  );
}

export function Queue({
  items,
  counts,
  selected,
  cleared,
  onSelect,
}: {
  items: QueueItem[];
  counts: ReconcileQueue["counts"];
  selected: number | null;
  cleared: number;
  onSelect: (poId: number) => void;
}) {
  return (
    <Stack gap={6}>
      <Group justify="space-between" px={6}>
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Queue
        </Text>
        <Text size="xs" c="dimmed">
          {counts.total} left{cleared > 0 ? ` · ${cleared} cleared` : ""}
        </Text>
      </Group>

      <ScrollArea.Autosize mah="calc(100vh - 200px)" type="hover">
        <Stack gap="xs" pr="xs">
          {GROUPS.map((g) => (
            <Section
              key={g.stage}
              label={g.label}
              rows={items.filter((i) => i.stage === g.stage)}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
          {items.length === 0 && (
            <Text size="sm" c="dimmed" p="md" ta="center">
              Nothing needs reconciling. 🎉
            </Text>
          )}
          {counts.unlinked_no_candidate > 0 && (
            <Text size="xs" c="dimmed" px={6} pt={4}>
              + {counts.unlinked_no_candidate} unlinked with no candidate — run matching after a sync
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>
    </Stack>
  );
}
