import type { ReactNode } from "react";
import { Group, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { IconHelpCircle } from "@tabler/icons-react";

interface SectionCardProps {
  title?: ReactNode;
  /** small print under the title */
  subtitle?: ReactNode;
  /** hover-help on a (?) icon next to the title */
  help?: string;
  /** right-aligned controls in the header row */
  actions?: ReactNode;
  children: ReactNode;
  /** drop the card chrome, keep the header + spacing (for nesting) */
  plain?: boolean;
  padding?: string | number;
}

/**
 * The one section container: bordered surface + a consistent header row. Replaces
 * the mix of `<Paper>` / `<Card>` with drifting padding and loose
 * `<Text size="sm" c="dimmed">` headings scattered across pages.
 */
export function SectionCard({
  title,
  subtitle,
  help,
  actions,
  children,
  plain = false,
  padding = "lg",
}: SectionCardProps) {
  const header = (title || actions) && (
    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
      {title && (
        <div>
          <Group gap={6} wrap="nowrap">
            <Text component="h3" fz="sm" fw={650} c="var(--gp-ink)" m={0}>
              {title}
            </Text>
            {help && (
              <Tooltip label={help} multiline w={260} withArrow>
                <IconHelpCircle
                  size={14}
                  style={{ color: "var(--mantine-color-dimmed)", cursor: "help" }}
                  aria-label={help}
                />
              </Tooltip>
            )}
          </Group>
          {subtitle && (
            <Text fz="xs" c="dimmed" mt={2}>
              {subtitle}
            </Text>
          )}
        </div>
      )}
      {actions && <Group gap="xs">{actions}</Group>}
    </Group>
  );

  const body = (
    <Stack gap="sm">
      {header}
      {children}
    </Stack>
  );

  if (plain) return body;

  return (
    <Paper withBorder radius="md" p={padding} bg="var(--gp-surface)">
      {body}
    </Paper>
  );
}
