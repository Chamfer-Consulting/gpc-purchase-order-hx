import type { ReactNode } from "react";
import { Badge, Button, Popover } from "@mantine/core";
import { IconChevronDown } from "@tabler/icons-react";

/**
 * One filter on the desktop scope bar: a fixed-height bordered button that opens
 * a popover. Every pill is the same shape, so the row always aligns no matter how
 * many values are picked — the selection shows as a count badge, not as pills
 * that grow the control.
 */
export function FilterPill({
  label,
  value,
  count = 0,
  width = 260,
  children,
}: {
  /** static name, e.g. "Customers" */
  label: string;
  /** when set, replaces the label — e.g. the resolved date range */
  value?: string;
  count?: number;
  width?: number;
  children: ReactNode;
}) {
  const active = count > 0 || !!value;
  return (
    <Popover width={width} position="bottom-start" shadow="md" trapFocus withinPortal>
      <Popover.Target>
        <Button
          size="xs"
          variant={active ? "light" : "default"}
          color={active ? "gpGreen" : "gray"}
          rightSection={<IconChevronDown size={13} />}
          styles={{ label: { fontWeight: 500 } }}
        >
          {value ?? label}
          {count > 0 && (
            <Badge size="xs" circle ml={6} variant="filled" color="gpGreen">
              {count}
            </Badge>
          )}
        </Button>
      </Popover.Target>
      <Popover.Dropdown p="xs">{children}</Popover.Dropdown>
    </Popover>
  );
}
