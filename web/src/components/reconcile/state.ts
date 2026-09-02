import type { ReconcilePoView, Stage } from "@/api/reconcile";

export type StageState = "done" | "active" | "attention" | "na";

export const STAGE_ORDER: Stage[] = ["extraction", "lifecycle", "match"];

export const STAGE_LABEL: Record<Stage, string> = {
  extraction: "Extraction",
  lifecycle: "Lifecycle",
  match: "Match",
};

/** Per-stage state for the tracker, derived purely from the PO view.
 *  `attention` = needs input; the workbench promotes the focused one to `active`. */
export function stageStates(view: ReconcilePoView): Record<Stage, StageState> {
  const ext = view.extraction;
  const extraction: StageState = ext.verdict || ext.revision_of ? "done" : "attention";

  const confirmed = view.links.some((l) => l.confirmed);
  const match: StageState = confirmed
    ? "done"
    : view.candidates.length > 0
      ? "attention"
      : "na";

  const status = view.header.status ?? "active";
  const lifecycle: StageState = status === "active" ? "na" : "done";

  return { extraction, lifecycle, match };
}

/** Which stage to focus when the PO first opens. Prefer the queue's own
 *  earliest-unresolved stage when it still needs attention, then extraction,
 *  then match, else fall back to the queue stage / extraction. */
export function blockingStage(view: ReconcilePoView, queueStage?: Stage): Stage {
  const s = stageStates(view);
  if (queueStage && s[queueStage] === "attention") return queueStage;
  if (s.extraction === "attention") return "extraction";
  if (s.match === "attention") return "match";
  return queueStage ?? "extraction";
}
