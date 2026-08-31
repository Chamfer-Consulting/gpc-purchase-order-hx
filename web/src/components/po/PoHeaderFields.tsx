import { Group, NumberInput, Text, TextInput } from "@mantine/core";
import type { PoHeader } from "@/api/poEdit";
import { fmtCurrency } from "@/lib/format";
import { NUMERIC_STYLE } from "@/theme/tokens";

const num = (v: unknown): number | null => {
  const x = typeof v === "number" ? v : v === "" || v == null ? null : Number(v);
  return x == null || Number.isNaN(x) ? null : x;
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Client-side header validation — { field: message }. Merge with any server
 *  (422) field errors before passing to <PoHeaderFields errors={...} />. */
export function headerErrors(h: Partial<PoHeader>, opts?: { requireIdentity?: boolean }): Record<string, string> {
  const e: Record<string, string> = {};
  if (opts?.requireIdentity) {
    if (!(h.po_number ?? "").trim() && !(h.customer_name ?? "").trim()) {
      e.po_number = "Give a PO number or a customer";
    }
  }
  for (const k of ["po_date", "delivery_date"] as const) {
    const v = (h[k] ?? "").trim();
    if (v && !DATE_RE.test(v)) e[k] = "Use YYYY-MM-DD";
  }
  return e;
}

interface Props {
  value: Partial<PoHeader>;
  onChange: (patch: Partial<PoHeader>) => void;
  errors?: Record<string, string>;
  disabled?: boolean;
}

export function PoHeaderFields({ value, onChange, errors = {}, disabled = false }: Props) {
  const set = (k: keyof PoHeader, v: unknown) => onChange({ [k]: v });

  const sub = num(value.subtotal);
  const tax = num(value.tax);
  const total = num(value.total);
  const totalsOff =
    sub != null && tax != null && total != null && Math.abs(sub + tax - total) > 0.02;

  return (
    <>
      <Group grow>
        <TextInput
          label="PO number"
          disabled={disabled}
          error={errors.po_number}
          value={value.po_number ?? ""}
          onChange={(e) => set("po_number", e.currentTarget.value)}
        />
        <TextInput
          label="Customer"
          disabled={disabled}
          error={errors.customer_name}
          value={value.customer_name ?? ""}
          onChange={(e) => set("customer_name", e.currentTarget.value)}
        />
      </Group>
      <Group grow>
        <TextInput
          label="PO date"
          placeholder="YYYY-MM-DD"
          disabled={disabled}
          error={errors.po_date}
          value={value.po_date ?? ""}
          onChange={(e) => set("po_date", e.currentTarget.value)}
        />
        <TextInput
          label="Delivery date"
          placeholder="YYYY-MM-DD"
          disabled={disabled}
          error={errors.delivery_date}
          value={value.delivery_date ?? ""}
          onChange={(e) => set("delivery_date", e.currentTarget.value)}
        />
      </Group>
      <Group grow align="flex-start">
        <NumberInput
          label="Subtotal"
          decimalScale={2}
          disabled={disabled}
          value={value.subtotal ?? undefined}
          onChange={(v) => set("subtotal", v === "" ? null : Number(v))}
        />
        <NumberInput
          label="Tax"
          decimalScale={2}
          disabled={disabled}
          value={value.tax ?? undefined}
          onChange={(v) => set("tax", v === "" ? null : Number(v))}
        />
        <NumberInput
          label="Total"
          decimalScale={2}
          disabled={disabled}
          error={errors.total}
          value={value.total ?? undefined}
          onChange={(v) => set("total", v === "" ? null : Number(v))}
        />
      </Group>
      {totalsOff && (
        <Text size="xs" c="orange" style={NUMERIC_STYLE}>
          Subtotal + tax = {fmtCurrency((sub ?? 0) + (tax ?? 0))}, but total is{" "}
          {fmtCurrency(total)}.
        </Text>
      )}
    </>
  );
}
