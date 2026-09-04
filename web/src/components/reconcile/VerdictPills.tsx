import { Button, Group, Text } from "@mantine/core";
import type { ReconcilePoView } from "@/api/reconcile";
import { useMe } from "@/api/me";
import { fmtDateOnly } from "@/lib/datetime";
import { RevisionOfInput, useExtractionDecision, type Verdict } from "./extraction";

const PILLS: { v: Verdict; label: string; key: string }[] = [
  { v: "is_po", label: "Looks right", key: "1" },
  { v: "not_po", label: "Not a PO", key: "2" },
  { v: "needs_fix", label: "Needs fix", key: "3" },
  { v: "revision", label: "Revision of…", key: "4" },
];

export function VerdictPills({ ctl, view }: { ctl: ReturnType<typeof useExtractionDecision>; view: ReconcilePoView }) {
  const { canEdit } = useMe();
  const ext = view.extraction;
  const decided = ext.verdict || ext.revision_of;

  return (
    <div>
      <Group gap={6} align="center">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" mr={2}>
          Verdict
        </Text>
        {PILLS.map((p) => {
          const active = ctl.verdict === p.v;
          return (
            <Button
              key={p.v}
              size="xs"
              radius="xl"
              variant={active ? "filled" : "default"}
              color={p.v === "not_po" ? "red" : undefined}
              disabled={!canEdit}
              loading={active && ctl.saving && p.v !== "revision"}
              onClick={() => ctl.pick(p.v)}
            >
              {p.label}
              <Text span size="10px" c={active ? undefined : "dimmed"} ml={5}>
                {p.key}
              </Text>
            </Button>
          );
        })}
        {decided && (
          <Text size="xs" c="dimmed" ml={4}>
            saved
            {ext.revision_of ? `: revision of ${ext.revision_of}` : ext.verdict ? `: ${ext.verdict}` : ""}
            {ext.decided_at ? ` · ${fmtDateOnly(ext.decided_at)}` : ""}
          </Text>
        )}
      </Group>

      {ctl.verdict === "revision" && (
        <Group gap="sm" align="flex-end" mt="xs">
          <RevisionOfInput
            view={view}
            value={ctl.revisionOf}
            onChange={ctl.setRevisionOf}
            disabled={!canEdit}
          />
          <Button
            size="xs"
            disabled={!canEdit || !ctl.revisionOf.trim()}
            loading={ctl.saving}
            onClick={() => ctl.save("revision")}
          >
            Confirm revision
          </Button>
        </Group>
      )}
    </div>
  );
}
