/*
 * Garfield Produce — the Mantine theme.
 *
 * Brand: hydroponic microgreen farm. Sprout green primary, deep "canopy" green
 * for nav chrome, harvest gold as a sparing accent, warm-paper neutrals. The
 * colour-blind-safe chart palette (src/charts/palette.ts, shared with the
 * backend) is deliberately NOT touched here — chrome and data-ink stay separate.
 *
 * Semantic tokens that Mantine has no home for live in ./tokens.css as
 * `--gp-*` custom properties.
 */
import {
  createTheme,
  rem,
  type CSSVariablesResolver,
  type MantineColorsTuple,
} from "@mantine/core";

const gpGreen: MantineColorsTuple = [
  "#eef6ee",
  "#dcebdd",
  "#b7d8b9",
  "#8fc492",
  "#6db070",
  "#57a65b",
  "#3c8d40", // 6 — primary (light)
  "#2f7333", // 7 — primary (dark) / hover
  "#265f2a",
  "#173d28",
];

const gpGold: MantineColorsTuple = [
  "#fdf6e7",
  "#f8e9c6",
  "#f0d491",
  "#e9c162",
  "#e3b03d",
  "#e0a32e", // 5
  "#c98f22", // 6
  "#a5741b",
  "#845c16",
  "#6b4a12",
];

// Canopy-tinted charcoals so dark mode reads as "night in the grow room", not
// the stock Mantine blue-grey. [7] = body, [6] = elevated surface, [4] = border.
const gpDark: MantineColorsTuple = [
  "#e3e8e4",
  "#c4ccc6",
  "#9aa89e",
  "#74837a",
  "#42504a",
  "#2e3a34",
  "#1c251f",
  "#141b16",
  "#101711",
  "#0b120d",
];

export const theme = createTheme({
  primaryColor: "gpGreen",
  primaryShade: { light: 6, dark: 7 },
  autoContrast: true,
  luminanceThreshold: 0.35,

  white: "#ffffff",
  black: "#1a1a17",

  fontFamily:
    "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
  fontFamilyMonospace:
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace",
  headings: {
    fontFamily: "'Sora Variable', 'Inter Variable', system-ui, sans-serif",
    fontWeight: "600",
    sizes: {
      h1: { fontSize: rem(28), lineHeight: "1.22", fontWeight: "700" },
      h2: { fontSize: rem(22), lineHeight: "1.28", fontWeight: "650" },
      h3: { fontSize: rem(18), lineHeight: "1.35", fontWeight: "600" },
      h4: { fontSize: rem(15), lineHeight: "1.4", fontWeight: "600" },
      h5: { fontSize: rem(13), lineHeight: "1.45", fontWeight: "600" },
      h6: { fontSize: rem(12), lineHeight: "1.45", fontWeight: "600" },
    },
  },

  defaultRadius: "md",
  radius: { xs: rem(4), sm: rem(7), md: rem(10), lg: rem(14), xl: rem(20) },

  shadows: {
    xs: "0 1px 2px rgba(18, 38, 24, 0.06)",
    sm: "0 1px 3px rgba(18, 38, 24, 0.09), 0 1px 2px rgba(18, 38, 24, 0.05)",
    md: "0 6px 16px rgba(18, 38, 24, 0.10)",
    lg: "0 14px 32px rgba(18, 38, 24, 0.14)",
    xl: "0 24px 52px rgba(18, 38, 24, 0.18)",
  },

  colors: {
    gpGreen,
    gpGold,
    dark: gpDark,
  },

  components: {
    Paper: { defaultProps: { radius: "md" } },
    Card: { defaultProps: { radius: "md", withBorder: true } },
    Button: { defaultProps: { radius: "md" } },
    ActionIcon: { defaultProps: { variant: "subtle" } },
    Badge: { defaultProps: { radius: "sm" } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 200 } },
    Modal: { defaultProps: { radius: "md", centered: true, overlayProps: { backgroundOpacity: 0.55, blur: 2 } } },
  },
});

// Warm-paper page ground with white cards (light); deep canopy ground with
// slightly-raised surfaces (dark). AppShell.Main paints `--gp-page`; Paper/Card
// keep `--mantine-color-body`.
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-body": "#ffffff",
    "--mantine-color-default-border": "#e4e3dc",
    "--mantine-color-dimmed": "#6e6c64",
  },
  dark: {
    "--mantine-color-body": "#16211a",
    "--mantine-color-default-border": "#2c352e",
  },
});
