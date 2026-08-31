import type { PoStatus } from "@/theme/tokens";

/** Mirror of backend services/po_admin.ALLOWED_TRANSITIONS — used to disable
 *  targets the server would reject anyway. Same-status (reason-only) is allowed. */
export const ALLOWED_TRANSITIONS: Record<PoStatus, PoStatus[]> = {
  active: ["draft", "cancelled", "withdrawn", "voided", "deleted"],
  draft: ["active", "deleted"],
  cancelled: ["active", "deleted"],
  withdrawn: ["active", "deleted"],
  voided: ["active", "deleted"],
  deleted: ["active"],
};

export function canTransition(from: PoStatus, to: PoStatus): boolean {
  return to === from || ALLOWED_TRANSITIONS[from]?.includes(to);
}

/** Options for a status Select given the current status. */
export function transitionOptions(from: PoStatus): { value: PoStatus; label: string }[] {
  const targets = new Set<PoStatus>([from, ...(ALLOWED_TRANSITIONS[from] ?? [])]);
  return [...targets].map((s) => ({ value: s, label: s }));
}
