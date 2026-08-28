/** Display formatters — the column-formatting counterpart to dashboard/labels.py. */

const usd0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const usd2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const fmtCurrency = (v: number | null | undefined, cents = false) =>
  v == null || Number.isNaN(v) ? "—" : (cents ? usd2 : usd0).format(v);

export const fmtInt = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : int.format(v);

export const fmtPercent = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : `${dec1.format(v)}%`;

export const fmtDelta = (v: number | null | undefined, kind: "int" | "currency" | "percent" = "int") => {
  if (v == null || Number.isNaN(v)) return null;
  const body =
    kind === "currency" ? fmtCurrency(Math.abs(v)) : kind === "percent" ? fmtPercent(Math.abs(v)) : fmtInt(Math.abs(v));
  return `${v >= 0 ? "+" : "−"}${body}`;
};

export type ColumnKind = "text" | "int" | "currency" | "currency2" | "percent" | "date";

export function formatCell(value: unknown, kind: ColumnKind): string {
  if (value == null || value === "") return "—";
  switch (kind) {
    case "int":
      return fmtInt(Number(value));
    case "currency":
      return fmtCurrency(Number(value));
    case "currency2":
      return fmtCurrency(Number(value), true);
    case "percent":
      return fmtPercent(Number(value));
    case "date":
      return String(value).slice(0, 10);
    default:
      return String(value);
  }
}
