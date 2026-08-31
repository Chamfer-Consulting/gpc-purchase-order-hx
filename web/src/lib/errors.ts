import { ApiError } from "./api";

/** Human message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  return "Something went wrong.";
}

/** FastAPI 422 field errors -> { "field_name": "message" } for form binding.
 *  The last path segment of `loc` is the field (loc is ["body", "header", "total"]). */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || !err.fields) return {};
  const out: Record<string, string> = {};
  for (const f of err.fields) {
    const key = String(f.loc[f.loc.length - 1] ?? "");
    if (key && !(key in out)) out[key] = f.msg;
  }
  return out;
}

export function isCode(err: unknown, code: string): boolean {
  return err instanceof ApiError && err.code === code;
}

export function isConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

export interface ConflictInfo {
  currentVersion?: number;
  editedBy?: string | null;
  editedAt?: string | null;
}

/** Payload of a 409 stale_write. */
export function conflictInfo(err: unknown): ConflictInfo {
  if (!(err instanceof ApiError) || !err.data) return {};
  const d = err.data;
  return {
    currentVersion: typeof d.current_version === "number" ? d.current_version : undefined,
    editedBy: (d.edited_by as string | null | undefined) ?? null,
    editedAt: (d.edited_at as string | null | undefined) ?? null,
  };
}

/** Allowed target statuses from a 422 bad_transition. */
export function allowedTransitions(err: unknown): string[] {
  if (!(err instanceof ApiError)) return [];
  const a = err.data?.allowed;
  return Array.isArray(a) ? (a as string[]) : [];
}
