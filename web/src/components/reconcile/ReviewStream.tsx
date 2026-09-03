import { Divider, Paper, Stack } from "@mantine/core";
import type { ReconcilePoView } from "@/api/reconcile";
import { ExtractionFailureCard } from "@/components/po/ExtractionFailureCard";
import { useMe } from "@/api/me";
import { OrderSource } from "./OrderSource";
import { MatchList } from "./MatchList";
import { LifecycleDisclosure } from "./LifecycleDisclosure";
import type { useExtractionDecision } from "./extraction";

/** One order, read top to bottom: the source → verdict → potential invoices →
 *  lifecycle. No columns, no tabs. */
export function ReviewStream({
  view,
  ext,
}: {
  view: ReconcilePoView;
  ext: ReturnType<typeof useExtractionDecision>;
}) {
  const { canEdit } = useMe();

  return (
    <Paper withBorder radius="lg" p="lg" bg="var(--gp-surface)">
      <Stack gap="lg">
        {view.header.error && (
          <ExtractionFailureCard poId={view.header.id} error={view.header.error} canEdit={canEdit} />
        )}

        <OrderSource view={view} ext={ext} />

        <Divider />
        <MatchList view={view} />

        <Divider />
        <LifecycleDisclosure view={view} />
      </Stack>
    </Paper>
  );
}
