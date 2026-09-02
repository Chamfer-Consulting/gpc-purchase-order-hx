import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Anchor,
  Box,
  Breadcrumbs,
  Group,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import { ErrorState } from "./ErrorState";

export interface Crumb {
  label: string;
  to?: string;
}

interface PageLayoutProps {
  title: string;
  description?: ReactNode;
  breadcrumbs?: Crumb[];
  /** right-aligned page actions (buttons) */
  actions?: ReactNode;
  /** the FilterBar; rendered in a sticky sub-bar under the header block */
  filterBar?: ReactNode;
  /** the ScopeBar / count strip */
  scope?: ReactNode;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** content column: "wide" (default, 1360), "form" (960), or "full" — up to the
   *  shell's 1600 bound, for dense split views like Reconcile */
  width?: "wide" | "form" | "full";
  children?: ReactNode;
}

const MAW: Record<NonNullable<PageLayoutProps["width"]>, number | undefined> = {
  wide: 1360,
  form: 960,
  full: undefined,
};

/**
 * Every route renders through this: breadcrumb → title row → optional sticky
 * filter bar → scope strip → skeleton | error | content. Replaces the per-page
 * `<Stack><Title order={2}>…</Title> {isLoading && <Loader/>} {error && <Alert/>}`
 * boilerplate (4 variants across ~10 pages).
 */
export function PageLayout({
  title,
  description,
  breadcrumbs,
  actions,
  filterBar,
  scope,
  loading = false,
  error,
  onRetry,
  width = "wide",
  children,
}: PageLayoutProps) {
  return (
    <Box maw={MAW[width]} mx={MAW[width] != null ? "auto" : undefined}>
      <Stack gap="md">
        {breadcrumbs && breadcrumbs.length > 0 && (
          <Breadcrumbs
            separator={<IconChevronRight size={13} style={{ color: "var(--mantine-color-dimmed)" }} />}
            separatorMargin={6}
          >
            {breadcrumbs.map((c, i) =>
              c.to ? (
                <Anchor key={i} component={Link} to={c.to} size="xs" c="dimmed">
                  {c.label}
                </Anchor>
              ) : (
                <Text key={i} size="xs" c="dimmed">
                  {c.label}
                </Text>
              ),
            )}
          </Breadcrumbs>
        )}

        <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
          <div style={{ minWidth: 0, flex: "1 1 auto" }}>
            <Title order={1} fz={{ base: 22, sm: 26 }}>
              {title}
            </Title>
            {description && (
              <Text size="sm" c="dimmed" mt={4} maw={640}>
                {description}
              </Text>
            )}
          </div>
          {actions && (
            <Group gap="xs" wrap="wrap" style={{ flexShrink: 0 }}>
              {actions}
            </Group>
          )}
        </Group>

        {filterBar && (
          <Box
            p={{ base: "6px 8px", sm: "8px 12px" }}
            style={{
              position: "sticky",
              top: 8,
              zIndex: 3,
              background: "var(--gp-surface-sunken)",
              border: "1px solid var(--mantine-color-default-border)",
              borderRadius: "var(--mantine-radius-md)",
            }}
          >
            {filterBar}
          </Box>
        )}

        {scope}

        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : loading ? (
          <PageSkeleton />
        ) : (
          children
        )}
      </Stack>
    </Box>
  );
}

/** KPI row + chart-grid shaped skeleton — the shared first-load state. */
export function PageSkeleton() {
  return (
    <Stack gap="lg" aria-busy="true" aria-label="Loading">
      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} h={104} radius="md" />
        ))}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <Skeleton h={280} radius="md" />
        <Skeleton h={280} radius="md" />
      </SimpleGrid>
      <Skeleton h={220} radius="md" />
    </Stack>
  );
}
