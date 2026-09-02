import { Group, Text, UnstyledButton } from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import type { ReconcilePoView, Stage } from "@/api/reconcile";
import { STAGE_LABEL, type StageState } from "./state";

function line(stage: Stage, view: ReconcilePoView): string {
  if (stage === "extraction") {
    const e = view.extraction;
    if (e.revision_of) return `revision of ${e.revision_of}`;
    if (e.verdict) return `decided: ${e.verdict}${e.decided_at ? ` · ${e.decided_at.slice(0, 10)}` : ""}`;
    return "no decision yet";
  }
  if (stage === "match") {
    const confirmed = view.links.filter((l) => l.confirmed);
    if (confirmed.length)
      return `confirmed: ${confirmed.map((l) => l.doc_number ?? l.invoice_id).join(", ")}`;
    const n = view.candidates.length;
    if (!n) return "no candidates";
    const top = view.candidates[0];
    return `${n} candidate${n === 1 ? "" : "s"} · top ${top.doc_number ?? top.invoice_id} · ${top.confidence}`;
  }
  // lifecycle
  const s = view.header.status ?? "active";
  return s === "active" ? "active" : `${s}${view.header.status_reason ? ` · ${view.header.status_reason}` : ""}`;
}

export function StageSummary({
  stage,
  state,
  view,
  onClick,
}: {
  stage: Stage;
  state: StageState;
  view: ReconcilePoView;
  onClick: () => void;
}) {
  const dot =
    state === "done"
      ? "var(--gp-status-good)"
      : state === "attention"
        ? "var(--mantine-color-orange-6)"
        : "var(--mantine-color-dimmed)";
  return (
    <UnstyledButton
      onClick={onClick}
      w="100%"
      px="sm"
      py={8}
      style={{
        borderRadius: "var(--mantine-radius-md)",
        border: "1px solid var(--mantine-color-default-border)",
        background: "var(--gp-surface)",
      }}
    >
      <Group gap="xs" wrap="nowrap">
        <IconChevronRight size={14} />
        <Text fz="xs" fw={700} tt="uppercase" c={dot}>
          {STAGE_LABEL[stage]}
        </Text>
        <Text fz="sm" c="dimmed" truncate style={{ flex: 1 }}>
          {line(stage, view)}
        </Text>
      </Group>
    </UnstyledButton>
  );
}
