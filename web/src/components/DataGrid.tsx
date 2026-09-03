import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Anchor, Button, Group, Table, Text, UnstyledButton } from "@mantine/core";
import { IconChevronDown, IconChevronUp, IconDownload, IconSelector } from "@tabler/icons-react";
import { formatCell, type ColumnKind } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";
import { EmptyState } from "./EmptyState";
import classes from "./DataGrid.module.css";

export interface Column<Row> {
  key: keyof Row & string;
  label: string;
  kind?: ColumnKind;
  align?: "left" | "right";
  /** build an SPA route from the row value, e.g. (v) => `/po/${v}` */
  linkTo?: (value: unknown, row: Row) => string;
}

export interface RowAction<Row> {
  label: string;
  onClick: (row: Row) => void;
  loading?: (row: Row) => boolean;
  disabled?: (row: Row) => boolean;
  /** don't render the button for this row at all */
  hidden?: (row: Row) => boolean;
}

interface DataGridProps<Row extends Record<string, unknown>> {
  rows: Row[];
  columns: Column<Row>[];
  /** trailing per-row action buttons (e.g. "Retry" on an extraction failure) */
  rowActions?: RowAction<Row>[];
  /** show a "Download CSV" button */
  exportName?: string;
  maxHeight?: number;
  minWidth?: number;
}

/**
 * Table wrapper: click-to-sort with aria-sort, right-aligned tabular numerics,
 * per-column formatting from lib/format, optional CSV export (formula-injection
 * guarded). Scrolls inside a Table.ScrollContainer.
 */
export function DataGrid<Row extends Record<string, unknown>>({
  rows,
  columns,
  rowActions,
  exportName,
  maxHeight = 480,
  minWidth = 520,
}: DataGridProps<Row>) {
  const hasActions = (rowActions?.length ?? 0) > 0;
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(true);

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, asc]);

  if (rows.length === 0) return <EmptyState label="No rows" compact />;

  function toggleSort(k: string) {
    if (sortKey === k) setAsc((v) => !v);
    else {
      setSortKey(k);
      setAsc(true);
    }
  }

  function downloadCsv() {
    const head = columns.map((c) => csvCell(c.label)).join(",");
    const body = sorted
      .map((r) => columns.map((c) => csvCell(r[c.key])).join(","))
      .join("\n");
    const blob = new Blob([`${head}\n${body}`], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportName ?? "export"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      {exportName && (
        <Group justify="flex-end" mb="xs">
          <Button
            size="xs"
            variant="light"
            leftSection={<IconDownload size={14} />}
            onClick={downloadCsv}
          >
            Download CSV
          </Button>
        </Group>
      )}
      <div className={classes.scrollWrap}>
      <Table.ScrollContainer minWidth={minWidth} maxHeight={maxHeight} type="native">
        <Table stickyHeader highlightOnHover verticalSpacing="xs" className={classes.table}>
          <Table.Thead className={classes.thead}>
            <Table.Tr>
              {columns.map((c, ci) => {
                const numeric =
                  c.align === "right" || (c.kind && c.kind !== "text" && c.kind !== "date");
                const active = sortKey === c.key;
                const SortIcon = !active ? IconSelector : asc ? IconChevronUp : IconChevronDown;
                return (
                  <Table.Th
                    key={c.key}
                    className={ci === 0 ? classes.stickyCol : undefined}
                    style={{ textAlign: numeric ? "right" : "left" }}
                    aria-sort={active ? (asc ? "ascending" : "descending") : "none"}
                  >
                    <UnstyledButton
                      className={classes.sortBtn}
                      style={{ justifyContent: numeric ? "flex-end" : "flex-start" }}
                      onClick={() => toggleSort(c.key)}
                    >
                      <span className={classes.thLabel}>{c.label}</span>
                      <SortIcon
                        size={13}
                        className={active ? classes.sortActive : classes.sortIdle}
                      />
                    </UnstyledButton>
                  </Table.Th>
                );
              })}
              {hasActions && <Table.Th aria-label="actions" />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sorted.map((r, i) => (
              <Table.Tr key={i}>
                {columns.map((c, ci) => {
                  const numeric =
                    c.align === "right" || (c.kind && c.kind !== "text" && c.kind !== "date");
                  return (
                    <Table.Td
                      key={c.key}
                      className={ci === 0 ? classes.stickyCol : undefined}
                      style={{ textAlign: numeric ? "right" : "left", ...(numeric ? NUMERIC_STYLE : null) }}
                    >
                      {c.linkTo && r[c.key] != null ? (
                        <Anchor component={Link} to={c.linkTo(r[c.key], r)} size="sm">
                          {formatCell(r[c.key], c.kind ?? "text")}
                        </Anchor>
                      ) : (
                        <Text size="sm">{formatCell(r[c.key], c.kind ?? "text")}</Text>
                      )}
                    </Table.Td>
                  );
                })}
                {hasActions && (
                  <Table.Td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <Group gap={6} justify="flex-end" wrap="nowrap">
                      {rowActions!
                        .filter((a) => !a.hidden?.(r))
                        .map((a) => (
                          <Button
                            key={a.label}
                            size="compact-xs"
                            variant="light"
                            loading={a.loading?.(r) ?? false}
                            disabled={a.disabled?.(r) ?? false}
                            onClick={() => a.onClick(r)}
                          >
                            {a.label}
                          </Button>
                        ))}
                    </Group>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      </div>
    </div>
  );
}

function csvCell(v: unknown): string {
  if (v == null) return "";
  let s = String(v);
  // Neutralise spreadsheet formula injection — some columns (email subject / from)
  // are attacker-controlled. Excel/Sheets treat a leading =,+,-,@ as a formula.
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
