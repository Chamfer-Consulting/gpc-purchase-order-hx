import { Alert, Button, Code, Group, Text } from "@mantine/core";
import { useRetryExtraction } from "@/api/poEdit";
import { errorMessage } from "@/lib/errors";

/** Shown when a PO row is an extraction failure rather than a real order — the
 *  stored error plus a one-click "Retry extraction" that re-runs the pipeline for
 *  its Gmail thread in-process. Used by the PO editor and the Reconcile detail
 *  pane; the Data Quality failures table triggers the same mutation inline. */
export function ExtractionFailureCard({
  poId,
  error,
  canEdit,
}: {
  poId: number;
  error: string;
  canEdit: boolean;
}) {
  const retry = useRetryExtraction(poId);
  const r = retry.data;

  const outcome =
    r?.status === "extracted"
      ? {
          color: "gpGreen",
          text: `Re-extracted${r.po_number ? ` — PO ${r.po_number}` : ""}${
            r.customer_name ? ` · ${r.customer_name}` : ""
          }.`,
        }
      : r?.status === "not_a_po"
        ? { color: "gray", text: "The model decided this thread isn't a purchase order." }
        : r?.status === "skipped"
          ? {
              color: "gray",
              text: "The pipeline filtered this thread out (no customer order in it). Mark it “Not a PO” on the reconcile screen.",
            }
          : r?.status === "error"
            ? { color: "red", text: `Failed again: ${r.error ?? "unknown error"}` }
            : null;

  return (
    <Alert color="red" variant="light" title="Extraction failed for this order">
      <Text size="sm">The extraction pipeline couldn't read an order off this email:</Text>
      <Code block fz={11} mt={6}>
        {error}
      </Code>
      <Text size="xs" c="dimmed" mt={6}>
        A transient failure (API / credit / timeout) can be retried. &ldquo;Not a purchase
        order&rdquo; and hand-edited rows can't.
      </Text>
      <Group mt="sm" gap="xs">
        <Button
          size="xs"
          color="red"
          variant="filled"
          loading={retry.isPending}
          disabled={!canEdit}
          onClick={() => retry.mutate()}
        >
          Retry extraction
        </Button>
        {retry.isError && (
          <Text size="xs" c="red">
            {errorMessage(retry.error)}
          </Text>
        )}
      </Group>
      {outcome && (
        <Text size="xs" c={outcome.color} mt={6} fw={500}>
          {outcome.text}
        </Text>
      )}
    </Alert>
  );
}
