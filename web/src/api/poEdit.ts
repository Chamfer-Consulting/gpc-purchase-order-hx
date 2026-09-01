import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "@/lib/api";

// Lifecycle-status vocabulary + its colour tag now live with the design tokens
// so every list/badge agrees. Re-exported here for existing importers.
import type { PoStatus } from "@/theme/tokens";
export { PO_STATUSES, STATUS_COLOR } from "@/theme/tokens";
export type { PoStatus };

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
  edited_by?: string | null;
  edited_at?: string | null;
  /** optimistic-concurrency counter — echo it back on every mutation */
  lock_version?: number;
  status?: PoStatus;
  status_reason?: string | null;
  status_at?: string | null;
  deleted_at?: string | null;
  /** set when this row is an extraction failure rather than a real order */
  error?: string | null;
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
    for (const key of [
      ["po", poId],
      ["data-quality"],
      ["overview"],
      ["matching"],
      // the /reconcile screen: a status change resolves / re-ranks a queue item
      ["reconcile-queue"],
      ["reconcile-po", poId],
    ]) {
      qc.invalidateQueries({ queryKey: key });
    }
  };
}

export function useSavePo(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    // the page maps 409 -> a conflict banner and 422 -> field errors itself
    meta: { silent: true },
    mutationFn: (body: {
      header: Partial<PoHeader>;
      items: PoLineItem[];
      removed_items: PoLineItem[];
      expected_version?: number | null;
    }) =>
      apiSend<{
        ok: boolean;
        math_check_failed: boolean;
        math_check_detail: string;
        lock_version: number;
      }>("POST", `/api/po/${poId}`, body),
    onSuccess: invalidate,
  });
}

export function useSetStatus(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { status: PoStatus; reason?: string | null; expected_version?: number | null }) =>
      apiSend<{ ok: boolean; header: PoHeader }>("POST", `/api/po/${poId}/status`, body),
    onSuccess: invalidate,
  });
}

export function useSoftDelete(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: { reason?: string | null; expected_version?: number | null }) =>
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
    mutationFn: (body: {
      line_id: number;
      voided: boolean;
      reason?: string | null;
      expected_version?: number | null;
    }) =>
      apiSend<{ ok: boolean; line: PoLineItem }>(
        "POST",
        `/api/po/${poId}/line/${body.line_id}/void`,
        { voided: body.voided, reason: body.reason, expected_version: body.expected_version },
      ),
    onSuccess: invalidate,
  });
}

export function useSetCustomer(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: {
      customer_name: string | null;
      customer_id?: string | null;
      expected_version?: number | null;
    }) => apiSend<{ ok: boolean; header: PoHeader }>("POST", `/api/po/${poId}/customer`, body),
    onSuccess: invalidate,
  });
}

export interface RetryExtractionResult {
  ok: boolean;
  /** "running" = the re-extraction is still going in the background; refetch shortly */
  status: "extracted" | "not_a_po" | "error" | "skipped" | "running";
  po_number?: string | null;
  customer_name?: string | null;
  error?: string;
  po?: PoDetail;
}

const RETRY_INVALIDATE_KEYS = (poId: number) => [
  ["po", poId],
  ["reconcile-po", poId],
  ["data-quality"],
  ["overview"],
  ["matching"],
  ["reconcile-queue"],
  ["archive"],
];

function invalidateRetry(qc: ReturnType<typeof useQueryClient>, poId: number, status: string) {
  for (const key of RETRY_INVALIDATE_KEYS(poId)) qc.invalidateQueries({ queryKey: key });
  // the child process is still working — refetch again once it's likely done
  if (status === "running") {
    setTimeout(() => {
      for (const key of RETRY_INVALIDATE_KEYS(poId)) qc.invalidateQueries({ queryKey: key });
    }, 45_000);
  }
}

/** Re-run the extraction pipeline for a PO row that recorded a transient failure.
 *  The server waits ~80s on the pipeline subprocess, then returns "running" if it
 *  hasn't finished (the child keeps going and writes the row). */
export function useRetryExtraction(poId: number) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true }, // caller shows the outcome inline
    mutationFn: () =>
      apiSend<RetryExtractionResult>("POST", `/api/po/${poId}/retry-extraction`),
    onSuccess: (d) => invalidateRetry(qc, poId, d.status),
  });
}

/** Same, but the PO id is the mutation argument — for list surfaces (Data Quality)
 *  that retry an arbitrary row. */
export function useRetryExtractionAny() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (poId: number) =>
      apiSend<RetryExtractionResult>("POST", `/api/po/${poId}/retry-extraction`),
    onSuccess: (d, poId) => invalidateRetry(qc, poId, d.status),
  });
}

export function useRegroup(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: {
      revision_of?: string | null;
      standalone?: boolean;
      expected_version?: number | null;
    }) => apiSend<{ ok: boolean }>("POST", `/api/po/${poId}/regroup`, body),
    onSuccess: invalidate,
  });
}

export function useLinkInvoice(poId: number) {
  const invalidate = useInvalidatePo(poId);
  return useMutation({
    mutationFn: (body: {
      invoice_id: number;
      replace_existing?: boolean;
      expected_version?: number | null;
    }) =>
      apiSend<{ ok: boolean; links: PoLink[] }>("POST", `/api/links`, {
        po_id: poId,
        invoice_id: body.invoice_id,
        replace_existing: body.replace_existing ?? false,
        expected_version: body.expected_version,
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

export interface PoHit {
  po_id: number;
  po_number: string | null;
  customer_name: string | null;
  po_date: string | null;
  total: number | null;
}

/** Latest-version PO lookup for the "revises PO" autocomplete. */
export function usePoSearch(search: string) {
  return useQuery({
    queryKey: ["po-search", search],
    queryFn: () => apiGet<PoHit[]>(`/api/pos`, { search, limit: 20 }),
    enabled: search.trim().length >= 2,
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
      for (const key of ["overview", "matching", "data-quality", "archive"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
