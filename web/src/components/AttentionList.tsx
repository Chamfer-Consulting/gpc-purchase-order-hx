import { Link } from "react-router-dom";
import { Badge, Card, Group, Text } from "@mantine/core";
import type { AttentionItem } from "@/api/schema";

const COLOR: Record<AttentionItem["severity"], string> = {
  critical: "red",
  serious: "orange",
  warning: "yellow",
  info: "blue",
};

export function AttentionList({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <Text size="sm" c="dimmed">
        Nothing needs attention right now.
      </Text>
    );
  }
  return (
    <Card withBorder radius="md" p="sm">
      {items.map((it, i) => {
        const body = (
          <Group gap="sm" wrap="nowrap" py={5}>
            <Badge color={COLOR[it.severity]} variant="light" w={78} style={{ flex: "none" }}>
              {it.severity}
            </Badge>
            <Text size="sm">{it.title}</Text>
          </Group>
        );
        return it.href ? (
          <Link
            key={i}
            to={it.href}
            style={{ textDecoration: "none", color: "inherit", display: "block" }}
          >
            {body}
          </Link>
        ) : (
          <div key={i}>{body}</div>
        );
      })}
    </Card>
  );
}
