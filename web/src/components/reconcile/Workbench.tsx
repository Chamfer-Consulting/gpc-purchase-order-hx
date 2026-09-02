import { Stack } from "@mantine/core";
import type { ReconcilePoView, Stage } from "@/api/reconcile";
import { stageStates, STAGE_ORDER } from "./state";
import { DecisionBar } from "./DecisionBar";
import { StageSummary } from "./StageSummary";
import { ExtractionBody, useExtractionDecision } from "./StageExtraction";
import { MatchBody } from "./StageMatch";
import { LifecycleBody } from "./StageLifecycle";

/** The redesigned reconcile detail pane: a sticky decision bar + a single
 *  focused stage's evidence + one-line summaries of the other two. Focus state
 *  lives in ReconcilePage so keyboard shortcuts can move it. */
export function Workbench({
  view,
  poId,
  focus,
  onFocus,
  onSkip,
}: {
  view: ReconcilePoView;
  poId: number;
  focus: Stage;
  onFocus: (s: Stage) => void;
  onSkip: () => void;
}) {
  const states = stageStates(view);
  const ext = useExtractionDecision(view);

  return (
    <Stack gap="md">
      <DecisionBar
        view={view}
        poId={poId}
        focus={focus}
        states={states}
        onFocus={onFocus}
        onSkip={onSkip}
        ext={ext}
      />

      {focus === "extraction" && <ExtractionBody view={view} />}
      {focus === "match" && <MatchBody view={view} />}
      {focus === "lifecycle" && <LifecycleBody view={view} />}

      {STAGE_ORDER.filter((s) => s !== focus).map((s) => (
        <StageSummary
          key={s}
          stage={s}
          state={states[s]}
          view={view}
          onClick={() => onFocus(s)}
        />
      ))}
    </Stack>
  );
}
