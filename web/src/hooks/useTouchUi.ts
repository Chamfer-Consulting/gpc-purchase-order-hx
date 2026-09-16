import { useMediaQuery } from "@mantine/hooks";

/** True for touch-primary devices (phones, tablets, kiosk touchscreens) —
 *  a `pointer: coarse` media query, not a width breakpoint, since a
 *  large-format touch tablet can be as wide as a small desktop monitor
 *  (see the Product Yields feature's "large format tablets" requirement).
 *  False for mouse/trackpad desktops, where the touch-sized UI (large
 *  fields, full-screen grid pickers) is oversized and awkward with a
 *  precise pointer. The `false` fallback covers first paint / SSR / no
 *  matchMedia — desktop-sized layout by default. */
export function useTouchUi(): boolean {
  return useMediaQuery("(pointer: coarse)", false) ?? false;
}
