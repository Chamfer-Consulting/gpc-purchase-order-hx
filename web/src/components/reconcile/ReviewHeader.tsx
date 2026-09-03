import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Popover,
  Progress,
  SegmentedControl,
  Text,
} from "@mantine/core";
import { IconChevronLeft, IconChevronRight, IconHelp, IconList } from "@tabler/icons-react";

export type ReviewFilter = "all" | "verdict" | "match";

export function ReviewHeader({
  position,
  total,
  cleared,
  filter,
  onFilter,
  counts,
  onPrev,
  onNext,
  onSkip,
  onJump,
  canPrev,
  canNext,
}: {
  position: number; // 1-based within the filtered list; 0 if none selected
  total: number; // filtered length
  cleared: number;
  filter: ReviewFilter;
  onFilter: (f: ReviewFilter) => void;
  counts: { extraction: number; match: number };
  onPrev: () => void;
  onNext: () => void;
  onSkip: () => void;
  onJump: () => void;
  canPrev: boolean;
  canNext: boolean;
}) {
  const pct = total ? (Math.max(position, 0) / total) * 100 : 0;
  return (
    <Box
      style={{
        position: "sticky",
        top: 8,
        zIndex: 5,
        background: "var(--gp-surface-sunken)",
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-md)",
        padding: "6px 10px",
      }}
    >
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Group gap={6} wrap="nowrap">
          <ActionIcon variant="default" size="sm" onClick={onPrev} disabled={!canPrev} aria-label="Previous">
            <IconChevronLeft size={15} />
          </ActionIcon>
          <ActionIcon variant="default" size="sm" onClick={onNext} disabled={!canNext} aria-label="Next">
            <IconChevronRight size={15} />
          </ActionIcon>
          <Text size="sm" fw={600} style={{ whiteSpace: "nowrap" }}>
            {position > 0 ? `${position} of ${total}` : `${total} to review`}
          </Text>
          {cleared > 0 && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
              · {cleared} cleared
            </Text>
          )}
        </Group>

        <SegmentedControl
          size="xs"
          value={filter}
          onChange={(v) => onFilter(v as ReviewFilter)}
          data={[
            { value: "all", label: "All" },
            { value: "verdict", label: `Needs verdict (${counts.extraction})` },
            { value: "match", label: `Needs match (${counts.match})` },
          ]}
        />

        <Group gap={6} wrap="nowrap">
          <Button size="xs" variant="default" onClick={onSkip}>
            Skip →
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<IconList size={13} />}
            onClick={onJump}
          >
            Queue
            <Text span size="10px" c="dimmed" ml={5}>
              ⌘K
            </Text>
          </Button>
          <Popover width={260} position="bottom-end" withArrow shadow="md">
            <Popover.Target>
              <ActionIcon variant="default" size="sm" aria-label="Keyboard shortcuts">
                <IconHelp size={15} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              <Text size="xs" fw={700} mb={4}>
                Shortcuts
              </Text>
              {[
                ["J / K", "next / previous order"],
                ["1 – 4", "set the verdict"],
                ["Y / N", "confirm / reject the best match"],
                ["E", "open the full editor"],
                ["S", "skip"],
                ["⌘K", "jump to any order"],
              ].map(([k, v]) => (
                <Group key={k} justify="space-between" gap="xs" wrap="nowrap">
                  <Badge size="xs" variant="light" color="gray">
                    {k}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    {v}
                  </Text>
                </Group>
              ))}
            </Popover.Dropdown>
          </Popover>
        </Group>
      </Group>

      <Progress value={pct} size={3} mt={6} radius={0} color="gpGreen" />
    </Box>
  );
}
