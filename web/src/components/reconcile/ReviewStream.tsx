import { Divider, Paper, Stack } from "@mantine/core";
import type { ReconcilePoView } from "@/api/reconcile";
import type { usePoEditForm } from "@/hooks/usePoEditForm";
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
  form,
}: {
  view: ReconcilePoView;
  ext: ReturnType<typeof useExtractionDecision>;
  /** the line-items editor state, owned by ReconcilePage (not OrderSource) so
   *  page-level navigation can guard against discarding a dirty edit */
  form: ReturnType<typeof usePoEditForm>;
}) {
  const { canEdit } = useMe();

  return (
    <Paper withBorder radius="lg" p="lg" bg="var(--gp-surface)">
      <Stack gap="lg">
        {view.header.error && (
          <ExtractionFailureCard poId={view.header.id} error={view.header.error} canEdit={canEdit} />
        )}

        <OrderSource view={view} ext={ext} form={form} />

        <Divider />
        <MatchList view={view} />

        <Divider />
        <LifecycleDisclosure view={view} />
      </Stack>
    </Paper>
  );
}
