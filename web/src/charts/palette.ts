/**
 * The house palette, ported verbatim from `shared/data.py` (LIGHT / DARK) — a
 * validated colour-blind-safe set. Same categorical order in both themes; only the
 * neutrals and grid swap. Keep in sync if `shared/data.py`'s palette ever changes.
 */
export interface Palette {
  categorical: string[];
  sequentialBlue: string[];
  status: { good: string; warning: string; serious: string; critical: string };
  inkPrimary: string;
  inkMuted: string;
  grid: string;
  surface: string;
  pagePlane: string;
}

export const LIGHT: Palette = {
  categorical: [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
  ],
  sequentialBlue: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  status: { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" },
  inkPrimary: "#0b0b0b",
  inkMuted: "#898781",
  grid: "#e1e0d9",
  surface: "#fcfcfb",
  pagePlane: "#f9f9f7",
};

export const DARK: Palette = {
  categorical: [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
  ],
  sequentialBlue: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  status: { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" },
  inkPrimary: "#ffffff",
  inkMuted: "#898781",
  grid: "#2c2c2a",
  surface: "#1a1a19",
  pagePlane: "#0d0d0d",
};

export const FONT_FAMILY =
  "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

/** Fixed hue per category (alphabetical), matching data.py:color_map_for(). */
export function colorMapFor(categories: string[], p: Palette): Record<string, string> {
  const ordered = [...new Set(categories)].sort((a, b) => a.localeCompare(b));
  const out: Record<string, string> = {};
  ordered.forEach((c, i) => {
    out[c] = p.categorical[i] ?? p.inkMuted;
  });
  return out;
}
