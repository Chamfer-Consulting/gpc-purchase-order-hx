import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend, fetchBlobUrl } from "@/lib/api";

export interface PoDocument {
  id: number;
  po_id: number;
  invoice_id: number | null;
  kind: "po_pdf" | "invoice_pdf" | "email_pdf" | "other";
  source: "gmail" | "qbo" | "upload";
  filename: string;
  mime_type: string;
  byte_size: number;
  content_hash: string;
  captured_at: string | null;
  captured_by: string | null;
}

interface CaptureResult {
  stored: PoDocument[];
  skipped: string[];
  note: string;
}
export interface CaptureResponse {
  ok: boolean;
  gmail?: CaptureResult;
  qbo?: CaptureResult;
}

export interface DocStorageStatus {
  mode: "supabase" | "inline";
  bucket: string;
  /** live bucket check: true/false, or null when Storage isn't configured */
  reachable: boolean | null;
  error: string | null;
  counts: { in_storage: number; inline: number; total: number };
}

export function useDocStorageStatus() {
  return useQuery({
    queryKey: ["doc-storage-status"],
    queryFn: () => apiGet<DocStorageStatus>("/api/po/documents/storage"),
    staleTime: 60_000,
  });
}

export function usePoDocuments(poId: number) {
  return useQuery({
    queryKey: ["po-docs", poId],
    queryFn: () => apiGet<PoDocument[]>(`/api/po/${poId}/documents`),
    enabled: Number.isFinite(poId),
  });
}

export function useCaptureDocs(poId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sources: ("gmail" | "qbo")[]) =>
      apiSend<CaptureResponse>("POST", `/api/po/${poId}/documents/capture`, { sources }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["po-docs", poId] });
      qc.invalidateQueries({ queryKey: ["po", poId] });
    },
  });
}

export function useUploadDoc(poId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const b64 = await fileToBase64(file);
      return apiSend<{ ok: boolean; document: PoDocument }>(
        "POST",
        `/api/po/${poId}/documents/upload`,
        { filename: file.name, content_b64: b64, mime_type: file.type || "application/pdf" },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["po-docs", poId] });
      qc.invalidateQueries({ queryKey: ["po", poId] });
    },
  });
}

export interface BackfillBucket {
  scanned: number;
  captured: number;
  failed: number;
  remaining: number;
  errors: string[];
  /** the sweep hit its time/row budget with work still queued — call again */
  more: boolean;
}
export interface BackfillResponse {
  ok: boolean;
  gmail?: BackfillBucket;
  qbo?: BackfillBucket;
}

export function useBackfillDocs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { sources: ("gmail" | "qbo")[]; limit?: number; continued?: boolean }) =>
      apiSend<BackfillResponse>("POST", "/api/po/documents/backfill", {
        sources: body.sources,
        limit: body.limit ?? 200,
        continued: body.continued ?? false,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["po-docs"] }),
  });
}

export function useDeleteDoc(poId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: number) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/po/${poId}/documents/${docId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["po-docs", poId] });
      qc.invalidateQueries({ queryKey: ["po", poId] });
    },
  });
}

/** Fetch the PDF (with auth) and open it in a new tab. */
export async function openDocument(poId: number, docId: number): Promise<void> {
  const url = await fetchBlobUrl(`/api/po/${poId}/documents/${docId}`);
  window.open(url, "_blank", "noopener");
  // give the tab time to load before releasing the blob
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const res = String(reader.result);
      resolve(res.slice(res.indexOf(",") + 1)); // strip the data: URL prefix
    };
    reader.readAsDataURL(file);
  });
}
