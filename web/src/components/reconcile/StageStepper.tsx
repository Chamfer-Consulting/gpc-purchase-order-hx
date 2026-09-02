import { Group, Text, UnstyledButton } from "@mantine/core";
import { IconCheck, IconMinus } from "@tabler/icons-react";
import type { Stage } from "@/api/reconcile";
import { STAGE_LABEL, STAGE_ORDER, type StageState } from "./state";

const DOT: Record<StageState, { char: string; color: string }> = {
  done: { char: "", color: "var(--gp-status-good)" },
  active: { char: "●", color: "var(--gp-accent)" },
  attention: { char: "○", color: "var(--mantine-color-orange-6)" },
  na: { char: "–", color: "var(--mantine-color-dimmed)" },
};

export function StageStepper({
  states,
  focus,
  onFocus,
}: {
  states: Record<Stage, StageState>;
  focus: Stage;
  onFocus: (s: Stage) => void;
}) {
  return (
    <Group gap={4} wrap="nowrap">
      {STAGE_ORDER.map((s, i) => {
        const st = states[s];
        const meta = DOT[st];
        const focused = s === focus;
        return (
          <Group key={s} gap={4} wrap="nowrap">
            {i > 0 && (
              <Text c="dimmed" fz={11} px={2}>
                ›
              </Text>
            )}
            <UnstyledButton
              onClick={() => onFocus(s)}
              px={8}
              py={3}
              style={{
                borderRadius: "var(--mantine-radius-sm)",
                background: focused ? "var(--gp-surface-sunken)" : "transparent",
                borderBottom: focused
                  ? "2px solid var(--gp-accent)"
                  : "2px solid transparent",
                whiteSpace: "nowrap",
              }}
            >
              <Group gap={5} wrap="nowrap">
                {st === "done" ? (
                  <IconCheck size={13} color={meta.color} />
                ) : st === "na" ? (
                  <IconMinus size={13} color={meta.color} />
                ) : (
                  <Text fz={12} c={meta.color} lh={1}>
                    {meta.char}
                  </Text>
                )}
                <Text
                  fz="xs"
                  fw={focused ? 700 : 500}
                  c={st === "na" && !focused ? "dimmed" : undefined}
                >
                  {STAGE_LABEL[s]}
                </Text>
              </Group>
            </UnstyledButton>
          </Group>
        );
      })}
    </Group>
  );
}
