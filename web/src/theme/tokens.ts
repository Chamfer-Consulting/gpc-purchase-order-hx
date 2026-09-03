/*
 * Non-visual design tokens: the one place severity / lifecycle-status → colour
 * is decided, so `AttentionList`, `SettingsPage` callbacks, review badges and PO
 * status tags all agree. Colour *values* for chrome live in ./tokens.css as
 * `--gp-*`; this file maps domain concepts onto Mantine colour names.
 */

export type Severity = "critical" | "serious" | "warning" | "info" | "success";

/** Severity → Mantine colour name (Alert/Badge/ThemeIcon `color` prop). */
export const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "red",
  serious: "orange",
  warning: "gpGold",
  info: "blue",
  success: "gpGreen",
};

/** Severity → the matching `--gp-status-*` custom property (raw CSS colour). */
export const SEVERITY_VAR: Record<Severity, string> = {
  critical: "var(--gp-status-critical)",
  serious: "var(--gp-status-serious)",
  warning: "var(--gp-status-warning)",
  info: "var(--gp-status-info)",
  success: "var(--gp-status-good)",
};

export type PoStatus =
  | "active"
  | "draft"
  | "cancelled"
  | "withdrawn"
  | "voided"
  | "deleted";

export const PO_STATUSES: PoStatus[] = [
  "active",
  "draft",
  "cancelled",
  "withdrawn",
  "voided",
  "deleted",
];

/** Colour per lifecycle status — the "tag" shown on a PO wherever it's listed. */
export const STATUS_COLOR: Record<PoStatus, string> = {
  active: "gpGreen",
  draft: "gray",
  cancelled: "orange",
  withdrawn: "gpGold",
  voided: "red",
  deleted: "red",
};

/** Shared inline style for numeric cells / figures (was re-inlined app-wide). */
export const NUMERIC_STYLE = { fontVariantNumeric: "tabular-nums" } as const;

/** `styles` prop for a NumberInput sitting in a right-aligned numeric column —
 *  keeps the typed figure under its right-aligned header. */
export const NUMERIC_INPUT_STYLES = {
  input: { textAlign: "right" as const, fontVariantNumeric: "tabular-nums" },
} as const;
