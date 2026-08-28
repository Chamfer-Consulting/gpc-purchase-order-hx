import { Badge, Stack, Text, Title } from "@mantine/core";

/** Every not-yet-ported page renders this until its phase. */
export function Placeholder({ name, phase }: { name: string; phase: string }) {
  return (
    <Stack>
      <Title order={2}>{name}</Title>
      <Badge variant="light" w="fit-content">
        {phase}
      </Badge>
      <Text c="dimmed" size="sm" maw={520}>
        Not yet migrated. Until then, use the Streamlit dashboard for this page — it stays
        live through Phase 4. See <code>docs/REBUILD-TODO.md</code>.
      </Text>
    </Stack>
  );
}
