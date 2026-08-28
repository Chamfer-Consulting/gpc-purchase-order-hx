import { Center, Text } from "@mantine/core";

export function EmptyState({
  label = "Nothing to show",
  height = 200,
}: {
  label?: string;
  height?: number | string;
}) {
  return (
    <Center
      h={height}
      style={{
        border: "1px dashed var(--mantine-color-default-border)",
        borderRadius: 10,
      }}
    >
      <Text size="sm" c="dimmed">
        {label}
      </Text>
    </Center>
  );
}
