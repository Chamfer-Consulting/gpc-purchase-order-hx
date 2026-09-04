import { useState } from "react";
import { Alert, SimpleGrid, Stack, Text, useComputedColorScheme } from "@mantine/core";
import { Chart } from "@/charts/Chart";
import {
  barOption,
  horizontalBarOption,
  lineOption,
  stackedBarOption,
} from "@/charts/options";
import { paletteFor } from "@/charts/theme";
import type { Palette } from "@/charts/palette";
import { useFilters } from "@/filters/useFilters";
import { AttentionList } from "./AttentionList";
import { ChartExportMenu } from "./ChartExportMenu";
import { DataGrid, type Column, type RowAction } from "./DataGrid";
import { KpiCard } from "./KpiCard";
import { ScopeBar } from "./ScopeBar";
import { SectionCard } from "./SectionCard";
import { formatCell } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/notify";
import { promptReason } from "@/lib/modals";
import { useAckLineMathAny, useRetryExtractionAny } from "@/api/poEdit";
import { useSetInvoiceHidden } from "@/api/settings";
import { PoFixModal } from "./po/PoFixModal";
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

function chartOption(c: ChartSpec, palette: Palette) {
  const fmt = c.y_format;
  switch (c.kind) {
    case "bar":
      return barOption(c.x, c.series, {
        fmt,
        breakdowns: c.breakdowns,
        palette,
        pointNotes: c.point_notes,
      });
    case "stacked_bar":
      return stackedBarOption(c.x, c.series, { fmt });
    case "hbar":
      return horizontalBarOption(
        c.x.map(String),
        (c.series[0]?.data ?? []).map((v) => v ?? 0),
        c.series[0]?.name,
        { fmt, breakdowns: c.breakdowns },
      );
    case "area":
      return lineOption(c.x, c.series, {
        area: true,
        palette,
        fmt,
        zoom: c.x.length > 24,
        breakdowns: c.breakdowns,
      });
    default:
      return lineOption(c.x, c.series, {
        palette,
        fmt,
        zoom: c.x.length > 24,
        breakdowns: c.breakdowns,
      });
  }
}

function columnLink(key: string): ((v: unknown) => string) | undefined {
  if (key === "po_id") return (v) => `/po/${v}`;
  // any customer column drills into that account's dossier
  if (key === "customer_name")
    return (v) => `/customers/${encodeURIComponent(String(v))}`;
  return undefined;
}

export function tableColumns(t: TableSpec): Column<Record<string, unknown>>[] {
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
      linkTo: columnLink(c.key),
    };
  });
}

/** Renders a backend PageResponse: scope → attention → KPIs → charts → tables.
 *  `hideTables` skips the generic table section — for a page that takes over
 *  rendering one of its tables itself (e.g. Explore's year-tabbed pivot). */
export function PageRenderer({
  data,
  showScope = true,
  hideTables = false,
}: {
  data: PageResponse;
  showScope?: boolean;
  hideTables?: boolean;
}) {
  const tableEntries = hideTables ? [] : Object.entries(data.tables);
  const { filters } = useFilters();
  const exportScope = (() => {
    const parts: string[] = [
      data.scope.start && data.scope.end
        ? `${data.scope.start.slice(0, 10)} – ${data.scope.end.slice(0, 10)}`
        : "All time",
    ];
    if (filters.customers.length)
      parts.push(`${filters.customers.length} customer${filters.customers.length > 1 ? "s" : ""}`);
    if (filters.products.length)
      parts.push(`${filters.products.length} product${filters.products.length > 1 ? "s" : ""}`);
    if (filters.sizes.length) parts.push(`${filters.sizes.length} size${filters.sizes.length > 1 ? "s" : ""}`);
    return parts.join("  ·  ");
  })();
  const palette = paletteFor(useComputedColorScheme("light"));
  const retry = useRetryExtractionAny();
  const ackMath = useAckLineMathAny();
  const setInvHidden = useSetInvoiceHidden();
  const [fixPoId, setFixPoId] = useState<number | null>(null);

  const fixAction: RowAction<AnyRow> = {
    label: "Fix",
    onClick: (r) => setFixPoId(Number(r.po_id)),
  };

  /** Inline row actions for the Data Quality tables:
   *  - "Retry" when a row carries po_id + error  (extraction-failures)
   *  - "Fix" when a row carries po_id + line_id  (math / price / no-size) — opens
   *    an editor modal for that PO's line items
   *  - "Acknowledge" additionally when the row is a math mismatch
   *  - "Exclude" when a row carries qbo_invoice_id + confidence (unsent invoices) */
  function rowActionsFor(rows: AnyRow[]): RowAction<AnyRow>[] | undefined {
    if (rows.some((r) => "qbo_invoice_id" in r && "confidence" in r)) {
      return [
        {
          label: "Exclude",
          loading: () => setInvHidden.isPending,
          disabled: () => setInvHidden.isPending,
          onClick: (r) =>
            promptReason({
              title: `Exclude invoice ${r.doc_number ?? r.qbo_invoice_id}?`,
              description:
                "It drops from every analytics page (revenue, customers, shipped, fulfilment). " +
                "Restore it any time under Settings → Visibility → Invoices.",
              label: "Reason (optional)",
              confirmLabel: "Exclude",
              onSubmit: (reason) =>
                setInvHidden.mutate(
                  { qbo_invoice_id: String(r.qbo_invoice_id), hidden: true, reason: reason ?? undefined },
                  {
                    onSuccess: () => notifySuccess("Excluded from analytics."),
                    onError: (e) => notifyError(e),
                  },
                ),
            }),
        },
      ];
    }

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
        fixAction,
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

    // price anomalies / no-size lines — just the editor
    if (rows.some((r) => "po_id" in r && "line_id" in r)) {
      return [fixAction];
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

      {data.kpis.length > 0 &&
        (() => {
          // the accent goes on the KPI the backend marks north_star; if none is
          // marked, fall back to the first (every page had one hero before).
          const marked = data.kpis.findIndex((k) => k.north_star);
          const heroIdx = marked >= 0 ? marked : 0;
          return (
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
                  northStar={i === heroIdx}
                />
              ))}
            </SimpleGrid>
          );
        })()}

      {data.charts.length > 0 && (
        <SimpleGrid cols={{ base: 1, lg: data.charts.length > 1 ? 2 : 1 }} spacing="lg">
          {data.charts.map((c) => {
            // an hbar with enough rows to want a taller card always goes
            // full-width — so it's never paired in a row with a fixed-height
            // chart it doesn't match (that mismatch is what made cards look
            // randomly different sizes). Anything sharing a row stays at the
            // one standard height.
            const tallHbar = c.kind === "hbar" && c.x.length > 10;
            const full =
              c.width === "full" ||
              (c.width == null &&
                (c.kind === "stacked_bar" || tallHbar || (c.kind !== "hbar" && c.x.length > 18)));
            const h = tallHbar ? Math.min(560, c.x.length * 26 + 48) : 300;
            const opt = chartOption(c, palette);
            const drawable = c.series.length > 0 && c.x.length > 0;
            return (
              <SectionCard
                key={c.id}
                title={c.title || undefined}
                style={full ? { gridColumn: "1 / -1" } : undefined}
                actions={
                  drawable && c.title ? (
                    <ChartExportMenu option={opt} title={c.title} scope={exportScope} />
                  ) : undefined
                }
              >
                <Chart option={opt} empty={!drawable} height={h} />
              </SectionCard>
            );
          })}
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

      <PoFixModal poId={fixPoId} onClose={() => setFixPoId(null)} />
    </Stack>
  );
}
