import { Group, Text } from "@mantine/core";
import { IconFilterCog } from "@tabler/icons-react";
import { NUMERIC_STYLE } from "@/theme/tokens";

interface ScopeBarProps {
  count: number;
  noun?: string;
  start?: string | null;
  end?: string | null;
  extra?: string;
}

/** "N orders in scope · 2026-01-01 – 2026-03-31" — the applied-filters summary. */
export function ScopeBar({ count, noun = "orders", start, end, extra }: ScopeBarProps) {
  const range = start && end ? `${start.slice(0, 10)} – ${end.slice(0, 10)}` : "all dates";
  return (
    <Group
      gap="xs"
      wrap="wrap"
      px="sm"
      py={6}
      style={{
        background: "var(--gp-surface-sunken)",
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-sm)",
      }}
    >
      <IconFilterCog size={14} style={{ color: "var(--mantine-color-dimmed)" }} />
      <Text size="sm" fw={600} style={NUMERIC_STYLE}>
        {count.toLocaleString()} {noun}
      </Text>
      <Text size="sm" c="dimmed">
        in scope · {range}
        {extra ? ` · ${extra}` : ""}
      </Text>
    </Group>
  );
}
