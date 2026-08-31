import { Link } from "react-router-dom";
import { Badge, Paper, Text, ThemeIcon } from "@mantine/core";
import {
  IconAlertTriangleFilled,
  IconChevronRight,
  IconInfoCircleFilled,
} from "@tabler/icons-react";
import type { AttentionItem } from "@/api/schema";
import { SEVERITY_COLOR, type Severity } from "@/theme/tokens";
import classes from "./AttentionList.module.css";

export function AttentionList({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <Text size="sm" c="dimmed">
        Nothing needs attention right now.
      </Text>
    );
  }

  return (
    <Paper withBorder radius="md" p={4} bg="var(--gp-surface)">
      <ul className={classes.list} aria-label="Needs attention">
        {items.map((it) => {
          const sev = it.severity as Severity;
          const Icon = sev === "info" ? IconInfoCircleFilled : IconAlertTriangleFilled;
          const inner = (
            <>
              <ThemeIcon variant="light" color={SEVERITY_COLOR[sev]} size={26} radius="md">
                <Icon size={15} />
              </ThemeIcon>
              <Text size="sm" fw={500} style={{ flex: 1, minWidth: 0 }}>
                {it.title}
              </Text>
              {it.count > 0 && (
                <Badge color={SEVERITY_COLOR[sev]} variant="light" size="sm">
                  {it.count.toLocaleString()}
                </Badge>
              )}
              {it.href && (
                <IconChevronRight size={15} style={{ color: "var(--mantine-color-dimmed)", flex: "none" }} />
              )}
            </>
          );
          return (
            <li key={`${it.severity}:${it.title}`} className={classes.row}>
              {it.href ? (
                <Link to={it.href} className={classes.link}>
                  {inner}
                </Link>
              ) : (
                <div className={classes.link}>{inner}</div>
              )}
            </li>
          );
        })}
      </ul>
    </Paper>
  );
}
