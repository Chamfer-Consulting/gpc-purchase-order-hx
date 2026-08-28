import { useMemo, useState } from "react";
import { Button, Group, Table, Text, UnstyledButton } from "@mantine/core";
import { formatCell, type ColumnKind } from "@/lib/format";
import { EmptyState } from "./EmptyState";

export interface Column<Row> {
  key: keyof Row & string;
  label: string;
  kind?: ColumnKind;
  align?: "left" | "right";
}

interface DataGridProps<Row extends Record<string, unknown>> {
  rows: Row[];
  columns: Column<Row>[];
  /** show a "Download CSV" button */
  exportName?: string;
  maxHeight?: number;
}

/**
 * Table wrapper: click-to-sort, right-aligned numerics, per-column formatting
 * from lib/format, optional CSV export. The data.py `data_grid` counterpart.
 */
export function DataGrid<Row extends Record<string, unknown>>({
  rows,
  columns,
  exportName,
  maxHeight = 480,
}: DataGridProps<Row>) {
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

  if (rows.length === 0) return <EmptyState label="No rows" />;

  function toggleSort(k: string) {
    if (sortKey === k) setAsc((v) => !v);
    else {
      setSortKey(k);
      setAsc(true);
    }
  }

  function downloadCsv() {
    const head = columns.map((c) => c.label).join(",");
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
          <Button size="xs" variant="default" onClick={downloadCsv}>
            Download CSV
          </Button>
        </Group>
      )}
      <div style={{ maxHeight, overflow: "auto" }}>
        <Table stickyHeader highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              {columns.map((c) => {
                const numeric = c.align === "right" || (c.kind && c.kind !== "text" && c.kind !== "date");
                return (
                  <Table.Th key={c.key} style={{ textAlign: numeric ? "right" : "left" }}>
                    <UnstyledButton
                      onClick={() => toggleSort(c.key)}
                      style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}
                    >
                      {c.label}
                      {sortKey === c.key ? (asc ? " ▲" : " ▼") : ""}
                    </UnstyledButton>
                  </Table.Th>
                );
              })}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sorted.map((r, i) => (
              <Table.Tr key={i}>
                {columns.map((c) => {
                  const numeric = c.align === "right" || (c.kind && c.kind !== "text" && c.kind !== "date");
                  return (
                    <Table.Td
                      key={c.key}
                      style={{ textAlign: numeric ? "right" : "left", fontVariantNumeric: "tabular-nums" }}
                    >
                      <Text size="sm">{formatCell(r[c.key], c.kind ?? "text")}</Text>
                    </Table.Td>
                  );
                })}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    </div>
  );
}

function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
