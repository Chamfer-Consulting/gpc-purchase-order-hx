/** Mirror of backend/app/schemas.py:PageResponse — keep in sync. */

export type NumFormat = "int" | "currency" | "currency2" | "percent" | "text";

export interface Kpi {
  label: string;
  value: number | string;
  format: NumFormat;
  delta?: string | null;
  delta_direction?: "up" | "down" | "flat" | null;
  delta_label?: string | null;
  spark?: number[] | null;
  help?: string | null;
  north_star?: boolean;
}

export interface ChartSeries {
  name: string;
  data: (number | null)[];
}

export interface BreakdownRow {
  name: string;
  value?: number | null;
  requested?: number | null;
  shipped?: number | null;
}

export interface ChartBreakdown {
  by: string;
  label: string;
  value_format?: NumFormat;
  points: { x: string | number; rows: BreakdownRow[] }[];
}

export interface ChartSpec {
  id: string;
  title?: string | null;
  kind: "line" | "area" | "bar" | "stacked_bar" | "hbar";
  x: (string | number)[];
  series: ChartSeries[];
  y_format: NumFormat;
  breakdowns?: ChartBreakdown[] | null;
  /** grid span: "full" = one column, "half" = paired. Omitted => auto by shape. */
  width?: "half" | "full";
  /** one extra tooltip line per x point, aligned to `x` */
  point_notes?: (string | null)[] | null;
}

export interface TableColumnSpec {
  key: string;
  label: string;
  kind: "text" | "int" | "currency" | "currency2" | "percent" | "date";
}

export interface TableSpec {
  title?: string | null;
  columns: TableColumnSpec[];
  rows: Record<string, unknown>[];
  export_name?: string | null;
}

export interface Scope {
  count: number;
  noun: string;
  start?: string | null;
  end?: string | null;
  note?: string | null;
}

export interface AttentionItem {
  severity: "critical" | "serious" | "warning" | "info";
  title: string;
  count: number;
  href?: string | null;
}

export interface PageResponse {
  stub: boolean;
  scope: Scope;
  attention: AttentionItem[];
  kpis: Kpi[];
  charts: ChartSpec[];
  tables: Record<string, TableSpec>;
  notes: string[];
}
