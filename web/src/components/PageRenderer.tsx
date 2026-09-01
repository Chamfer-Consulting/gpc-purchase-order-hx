import { Alert, SimpleGrid, Stack, Text } from "@mantine/core";
import { Chart } from "@/charts/Chart";
import {
  barOption,
  horizontalBarOption,
  lineOption,
  stackedBarOption,
} from "@/charts/options";
import { AttentionList } from "./AttentionList";
import { DataGrid, type Column, type RowAction } from "./DataGrid";
import { KpiCard } from "./KpiCard";
import { ScopeBar } from "./ScopeBar";
import { SectionCard } from "./SectionCard";
import { formatCell } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/notify";
import { promptReason } from "@/lib/modals";
import { useAckLineMathAny, useRetryExtractionAny } from "@/api/poEdit";
import type { ChartSpec, Kpi, PageResponse, TableSpec } from "@/api/schema";

type AnyRow = Record<string, unknown>;

/** Mirrors the backend guard: an errored PO row can be re-extracted unless the
 *  failure is a settled outcome. */
function isRetryableError(e: unknown): e is string {
  return (
    typeof e === "string" &&
    e.trim() !== "" &&
    e !== "not a purchase order" &&
    !e.startsWith("modification")
  );
}

function kpiValue(k: Kpi): string {
  return typeof k.value === "number" ? formatCell(k.value, k.format === "text" ? "text" : k.format) : String(k.value);
}

function chartOption(c: ChartSpec) {
  switch (c.kind) {
    case "bar":
      return barOption(c.x, c.series);
    case "stacked_bar":
      return stackedBarOption(c.x, c.series);
    case "hbar":
      return horizontalBarOption(
        c.x.map(String),
        (c.series[0]?.data ?? []).map((v) => v ?? 0),
        c.series[0]?.name,
      );
    case "area":
      return lineOption(c.x, c.series, { area: true });
    default:
      return lineOption(c.x, c.series);
  }
}

function tableColumns(t: TableSpec): Column<Record<string, unknown>>[] {
  return t.columns.map((c) => {
    // An id / row-key column is an identifier, never a magnitude — don't
    // thousands-group it ("23,692") or right-align it, even if the spec says int.
    const isIdentifier = c.key === "po_id" || c.key === "id" || c.key.endsWith("_id");
    const kind = isIdentifier ? "text" : c.kind;
    return {
      key: c.key,
      label: c.label,
      kind,
      align: kind !== "text" && kind !== "date" ? "right" : "left",
      linkTo: c.key === "po_id" ? (v: unknown) => `/po/${v}` : undefined,
    };
  });
}

/** Renders a backend PageResponse: scope → attention → KPIs → charts → tables. */
export function PageRenderer({ data, showScope = true }: { data: PageResponse; showScope?: boolean }) {
  const tableEntries = Object.entries(data.tables);
  const retry = useRetryExtractionAny();
  const ackMath = useAckLineMathAny();

  /** Inline row actions for the Data Quality tables:
   *  - "Retry" when a row carries po_id + error  (extraction-failures)
   *  - "Acknowledge" when a row carries po_id + line_id + math_mismatch (math checks) */
  function rowActionsFor(rows: AnyRow[]): RowAction<AnyRow>[] | undefined {
    if (rows.some((r) => "po_id" in r && "error" in r)) {
      return [
        {
          label: "Retry",
          hidden: (r) => !isRetryableError(r.error),
          loading: (r) => retry.isPending && retry.variables === Number(r.po_id),
          disabled: () => retry.isPending,
          onClick: (r) =>
            retry.mutate(Number(r.po_id), {
              onSuccess: (d) =>
                notifySuccess(
                  d.status === "extracted"
                    ? `Re-extracted PO ${d.po_number ?? r.po_id}.`
                    : d.status === "running"
                      ? "Re-extraction started — still running; the table refreshes when it's done."
                      : d.status === "not_a_po"
                        ? "The model decided it isn't a purchase order."
                        : d.status === "skipped"
                          ? "The pipeline filtered this thread out."
                          : `Still failing: ${d.error ?? "unknown error"}`,
                ),
              onError: (e) => notifyError(e),
            }),
        },
      ];
    }

    if (rows.some((r) => "po_id" in r && "line_id" in r && "math_mismatch" in r)) {
      return [
        {
          label: "Acknowledge",
          loading: () => ackMath.isPending,
          disabled: () => ackMath.isPending,
          onClick: (r) =>
            promptReason({
              title: "Acknowledge this math mismatch",
              description:
                "The arithmetic is genuinely off on the source document (vendor rounding, a " +
                "discount we don't model). It stays on record but drops out of this queue.",
              label: "Reason (optional)",
              confirmLabel: "Acknowledge",
              onSubmit: (reason) =>
                ackMath.mutate(
                  { po_id: Number(r.po_id), line_id: Number(r.line_id), ack: true, reason },
                  {
                    onSuccess: () => notifySuccess("Acknowledged — removed from the fix queue."),
                    onError: (e) => notifyError(e),
                  },
                ),
            }),
        },
      ];
    }

    return undefined;
  }

  return (
    <Stack gap="lg">
      {showScope && (
        <ScopeBar
          count={data.scope.count}
          noun={data.scope.noun}
          start={data.scope.start ?? undefined}
          end={data.scope.end ?? undefined}
          extra={data.scope.note ?? undefined}
        />
      )}

      {data.attention.length > 0 && <AttentionList items={data.attention} />}

      {data.stub && (
        <Alert color="yellow" variant="light" title="Preview">
          Some numbers on this page come from a service that isn't fully wired yet.
        </Alert>
      )}

      {data.notes.map((n, i) => (
        <Text key={i} size="sm" c="dimmed">
          {n}
        </Text>
      ))}

      {data.kpis.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, md: Math.min(4, data.kpis.length) }}>
          {data.kpis.map((k, i) => (
            <KpiCard
              key={k.label}
              label={k.label}
              value={kpiValue(k)}
              delta={k.delta ?? null}
              deltaDirection={k.delta_direction ?? undefined}
              deltaLabel={k.delta_label ?? undefined}
              help={k.help ?? undefined}
              spark={k.spark ?? undefined}
              northStar={i === 0}
            />
          ))}
        </SimpleGrid>
      )}

      {data.charts.length > 0 && (
        <SimpleGrid cols={{ base: 1, lg: data.charts.length > 1 ? 2 : 1 }} spacing="lg">
          {data.charts.map((c) => (
            <SectionCard key={c.id} title={c.title || undefined}>
              <Chart option={chartOption(c)} empty={c.series.length === 0 || c.x.length === 0} />
            </SectionCard>
          ))}
        </SimpleGrid>
      )}

      {tableEntries.map(([key, t]) => (
        <SectionCard key={key} title={t.title || undefined}>
          <DataGrid
            rows={t.rows}
            columns={tableColumns(t)}
            rowActions={rowActionsFor(t.rows as AnyRow[])}
            exportName={t.export_name ?? key}
          />
        </SectionCard>
      ))}
    </Stack>
  );
}
