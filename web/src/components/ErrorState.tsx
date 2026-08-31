import type { ReactNode } from "react";
import { Alert, Button, Skeleton, Stack, Text } from "@mantine/core";
import { IconAlertTriangle, IconRefresh } from "@tabler/icons-react";

interface ErrorStateProps {
  error: unknown;
  title?: string;
  /** wired to the query's refetch, when available */
  onRetry?: () => void;
  compact?: boolean;
}

function message(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Something went wrong loading this data.";
}

/** The one way this app shows a failed load — replaces ~4 ad-hoc variants. */
export function ErrorState({ error, title = "Couldn't load", onRetry, compact }: ErrorStateProps) {
  return (
    <Alert
      color="red"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      title={title}
      p={compact ? "sm" : "md"}
    >
      <Stack gap="xs" align="flex-start">
        <Text size="sm">{message(error)}</Text>
        {onRetry && (
          <Button
            size="xs"
            variant="light"
            color="red"
            leftSection={<IconRefresh size={14} />}
            onClick={onRetry}
          >
            Retry
          </Button>
        )}
      </Stack>
    </Alert>
  );
}

/**
 * Sub-panel async wrapper for the cases that aren't a whole page (Review tabs,
 * Settings cards, Explore's two blocks). Pass the react-query result slice.
 */
export function QueryBoundary({
  loading,
  error,
  onRetry,
  skeleton,
  children,
}: {
  loading: boolean;
  error: unknown;
  onRetry?: () => void;
  skeleton?: ReactNode;
  children: ReactNode;
}) {
  if (error) return <ErrorState error={error} onRetry={onRetry} compact />;
  if (loading) return <>{skeleton ?? <PanelSkeleton />}</>;
  return <>{children}</>;
}

export function PanelSkeleton() {
  return (
    <Stack gap="sm">
      <Skeleton h={18} w="40%" radius="sm" />
      <Skeleton h={120} radius="sm" />
      <Skeleton h={14} w="70%" radius="sm" />
    </Stack>
  );
}
