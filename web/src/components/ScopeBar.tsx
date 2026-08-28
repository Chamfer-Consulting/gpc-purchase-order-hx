import { Group, Text } from "@mantine/core";

interface ScopeBarProps {
  count: number;
  noun?: string;
  start?: string | null;
  end?: string | null;
  extra?: string;
}

/** The "N orders in scope · Jan 1 – Mar 31" strip above a page's charts. */
export function ScopeBar({ count, noun = "orders", start, end, extra }: ScopeBarProps) {
  const range =
    start && end ? `${start.slice(0, 10)} – ${end.slice(0, 10)}` : "all dates";
  return (
    <Group gap="xs" mb="md" wrap="wrap">
      <Text size="sm" fw={600} style={{ fontVariantNumeric: "tabular-nums" }}>
        {count.toLocaleString()} {noun}
      </Text>
      <Text size="sm" c="dimmed">
        in scope · {range}
        {extra ? ` · ${extra}` : ""}
      </Text>
    </Group>
  );
}
