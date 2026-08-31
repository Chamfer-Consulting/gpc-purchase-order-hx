import { Box, Text } from "@mantine/core";

interface BrandProps {
  /** overall mark height in px; wordmark scales with it */
  size?: number;
  /** hide the "Garfield Produce" wordmark, show just the sprout mark */
  markOnly?: boolean;
  /** render the wordmark in white (for the dark canopy header) */
  onDark?: boolean;
}

/** The sprout mark — a stem with two cotyledon leaves and a seed. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="Garfield Produce">
      <rect width="32" height="32" rx="8" fill="var(--gp-canopy)" />
      <path d="M16 25v-9" fill="none" stroke="#8fc492" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M16 17c0-4.4-3-7.4-8-7.9 0 4.9 3 8 8 7.9Z" fill="#3c8d40" />
      <path d="M16 15.5c.2-3.8 2.8-6.4 7-6.9-.1 4.2-2.8 6.9-7 6.9Z" fill="#6db070" />
      <circle cx="16" cy="8.4" r="2.1" fill="var(--gp-accent)" />
    </svg>
  );
}

export function Brand({ size = 28, markOnly = false, onDark = false }: BrandProps) {
  return (
    <Box style={{ display: "flex", alignItems: "center", gap: 10, lineHeight: 1 }}>
      <BrandMark size={size} />
      {!markOnly && (
        <Box style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <Text
            component="span"
            ff="'Sora Variable', system-ui, sans-serif"
            fw={700}
            fz={size * 0.58}
            lh={1.05}
            c={onDark ? "white" : undefined}
            style={{ letterSpacing: "-0.01em" }}
          >
            Garfield Produce
          </Text>
          <Text
            component="span"
            fz={size * 0.34}
            fw={600}
            tt="uppercase"
            style={{ letterSpacing: "0.14em", color: onDark ? "var(--gp-nav-section)" : "var(--mantine-color-dimmed)" }}
          >
            PO Dashboard
          </Text>
        </Box>
      )}
    </Box>
  );
}
