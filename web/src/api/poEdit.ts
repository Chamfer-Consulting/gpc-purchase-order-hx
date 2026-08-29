import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

export interface PoLineItem {
  id?: number;
  product_raw?: string | null;
  product_name?: string | null;
  container_size?: string | null;
  quantity?: number | null;
  unit_price?: number | null;
  line_total?: number | null;
  additional_cost?: number | null;
  sku?: string | null;
  is_sample?: boolean;
  math_mismatch?: string | null;
  price_anomaly?: string | null;
  revision_status?: string | null;
  voided?: boolean;
  void_reason?: string | null;
}

export type PoStatus =
  | "active"
  | "draft"
  | "cancelled"
  | "withdrawn"
  | "voided"
  | "deleted";

export const PO_STATUSES: PoStatus[] = [
  "active",
  "draft",
  "cancelled",
  "withdrawn",
  "voided",
  "deleted",
];

/** Colour per lifecycle status — the "tag" shown on a PO wherever it's listed. */
export const STATUS_COLOR: Record<PoStatus, string> = {
  active: "teal",
  draft: "gray",
  cancelled: "orange",
  withdrawn: "yellow",
  voided: "red",
  deleted: "red",
};

export interface PoHeader {
  id: number;
  source_file: string;
  po_number: string | null;
  po_date: string | null;
  delivery_date: string | null;
  customer_name: string | null;
  customer_id?: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  notes: string | null;
  edited: boolean;
  status?: PoStatus;
  status_reason?: string | null;
  status_at?: string | null;
  deleted_at?: string | null;
}

export interface PoRevision {
  po_id: number;
  po_number: string | null;
  customer_name: string | null;
  po_date: string | null;
  delivery_date: string | null;
  is_revision: boolean;
  revision_label: string | null;
  status: PoStatus;
  total: number | null;
  source_file: string;
}

export interface PoLink {
  invoice_id: number;
  match_method: string;
  match_score: number | null;
  confirmed: boolean;
  rejected: boolean;
  linked_at: string | null;
  doc_number: string | null;
  txn_date: string | null;
  total_amt: number | null;
  customer_name: string | null;
  qbo_url: string | null;
}

export interface PoSources {
  gmail_thread_url: string | null;
  drive_pdf_url: string | null;
}

export interface AuditEntry {
  id: number;
  actor: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string | null;
}

export interface InvoiceHit {
  invoice_id: number;
  doc_number: string | null;
  txn_date: string | null;
  total_amt: number | null;
  customer_name: string | null;
  linked: boolean;
}

export interface PoDetail {
  header: PoHeader;
  items: PoLineItem[];
  removed_items: PoLineItem[];
  revisions?: PoRevision[];
  links?: PoLink[];
  sources?: PoSources;
  audit?: AuditEntry[];
}

export function usePo(poId: number) {
  return useQuery({
    queryKey: ["po", poId],
    queryFn: () => apiGet<PoDetail>(`/api/po/${poId}`),
    enabled: Number.isFinite(poId),
  });
}

function useInvalidatePo(poId: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["po", poId] });
    qc.invalidateQueries({ queryKey: ["data-quality"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
    qc.invalidateQueries({ queryKey: ["matching"] });
  };
}

export function useSavePo(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: {
      header: Partial<PoHeader>;
      items: PoLineItem[];
      removed_items: PoLineItem[];
    }) =>
      apiSend<{ ok: boolean; math_check_failed: boolean; math_check_detail: string }>(
        "POST",
        `/api/po/${poId}`,
        body,
      ),
    onSuccess: invalidate,
  });
}

export function useSetStatus(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { status: PoStatus; reason?: string | null }) =>
      apiSend<{ ok: boolean; header: PoHeader }>("POST", `/api/po/${poId}/status`, body),
    onSuccess: invalidate,
  });
}

export function useSoftDelete(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { reason?: string | null }) =>
      apiSend<{ ok: boolean; header: PoHeader }>("DELETE", `/api/po/${poId}`, body),
    onSuccess: invalidate,
  });
}

export function useRestorePo(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: () =>
      apiSend<{ ok: boolean; header: PoHeader }>("POST", `/api/po/${poId}/restore`),
    onSuccess: invalidate,
  });
}

export function useVoidLine(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { line_id: number; voided: boolean; reason?: string | null }) =>
      apiSend<{ ok: boolean; line: PoLineItem }>(
        "POST",
        `/api/po/${poId}/line/${body.line_id}/void`,
        { voided: body.voided, reason: body.reason },
      ),
    onSuccess: invalidate,
  });
}

export function useSetCustomer(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { customer_name: string | null; customer_id?: string | null }) =>
      apiSend<{ ok: boolean; header: PoHeader }>("POST", `/api/po/${poId}/customer`, body),
    onSuccess: invalidate,
  });
}

export function useRegroup(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { revision_of?: string | null; standalone?: boolean }) =>
      apiSend<{ ok: boolean }>("POST", `/api/po/${poId}/regroup`, body),
    onSuccess: invalidate,
  });
}

export function useLinkInvoice(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { invoice_id: number; replace_existing?: boolean }) =>
      apiSend<{ ok: boolean; links: PoLink[] }>("POST", `/api/links`, {
        po_id: poId,
        invoice_id: body.invoice_id,
        replace_existing: body.replace_existing ?? false,
      }),
    onSuccess: invalidate,
  });
}

export function useUnlinkInvoice(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (invoiceId: number) =>
      apiSend<{ ok: boolean; links: PoLink[] }>(
        "DELETE",
        `/api/links?po_id=${poId}&invoice_id=${invoiceId}`,
      ),
    onSuccess: invalidate,
  });
}

export function useInvoiceSearch(search: string) {
  return useQuery({
    queryKey: ["invoice-search", search],
    queryFn: () => apiGet<InvoiceHit[]>(`/api/invoices`, { search, limit: 25 }),
    enabled: search.trim().length > 0,
    staleTime: 30_000,
  });
}

export interface ArchivedPo {
  po_id: number;
  po_number: string | null;
  customer_name: string | null;
  po_date: string | null;
  delivery_date: string | null;
  status: PoStatus;
  status_reason: string | null;
  status_at: string | null;
  deleted_at: string | null;
  total: number | null;
  source_file: string;
  edited_by: string | null;
  n_items: number;
}

export interface ArchiveResponse {
  rows: ArchivedPo[];
  counts: Record<string, number>;
}

export function useArchive(status?: string) {
  return useQuery({
    queryKey: ["archive", status ?? "all"],
    queryFn: () =>
      apiGet<ArchiveResponse>("/api/archive", status ? { status } : undefined),
    staleTime: 15_000,
  });
}

export function useCreatePo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { header: Partial<PoHeader>; items: PoLineItem[] }) =>
      apiSend<{ ok: boolean; po_id: number; detail: PoDetail }>("POST", `/api/po`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["page"] });
    },
  });
}
