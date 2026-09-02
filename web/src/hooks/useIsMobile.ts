import { useMediaQuery } from "@mantine/hooks";

/** true below Mantine's `sm` breakpoint (48em / 768px). The `false` fallback
 *  covers first paint / SSR / no matchMedia — desktop layout by default. */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 48em)", false) ?? false;
}
