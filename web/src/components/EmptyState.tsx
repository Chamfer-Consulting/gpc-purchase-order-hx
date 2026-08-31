import type { ReactNode } from "react";
import { Box, Stack, Text, ThemeIcon } from "@mantine/core";
import { IconInbox } from "@tabler/icons-react";

interface EmptyStateProps {
  /** short line — kept as `label` for back-compat with existing call sites */
  label?: string;
  title?: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  height?: number | string;
  compact?: boolean;
}

/** Neutral "nothing here" panel — dashed frame, centred, optional icon + action. */
export function EmptyState({
  label,
  title,
  description,
  icon,
  action,
  height,
  compact = false,
}: EmptyStateProps) {
  const heading = title ?? label ?? "Nothing to show";
  return (
    <Box
      style={{
        minHeight: height ?? (compact ? 96 : 180),
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        border: "1px dashed var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-md)",
        padding: compact ? "1rem" : "2rem 1.5rem",
        background: "var(--gp-surface-sunken)",
      }}
    >
      <Stack align="center" gap={compact ? 4 : 8} maw={340} ta="center">
        {!compact &&
          (icon ?? (
            <ThemeIcon variant="light" color="gray" size={40} radius="md">
              <IconInbox size={22} />
            </ThemeIcon>
          ))}
        <Text size="sm" fw={600} c="var(--gp-ink)">
          {heading}
        </Text>
        {description && (
          <Text size="xs" c="dimmed">
            {description}
          </Text>
        )}
        {action}
      </Stack>
    </Box>
  );
}
