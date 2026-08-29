"""Core logic for capturing the source PDFs behind a purchase order:

  * po_pdf       — the PDF attachment(s) on the PO's Gmail thread
  * invoice_pdf  — the rendered invoice PDF for each confirmed linked invoice,
    from QuickBooks' Print / Save-as-PDF endpoint
  * other        — a file attached by hand through the app

Plain psycopg2 + gmail_client / qbo_client — no FastAPI, no audit log. The API
layer (backend/app/services/po_docs.py) wraps these and adds audit rows; the
scheduled runner (run_doc_capture.py) calls them directly.

None of these functions commit — the caller owns the transaction. Bytes go to
Supabase Storage when doc_storage.is_enabled(), otherwise inline in
po_documents.content.
"""

import hashlib

import psycopg2
import psycopg2.extras

import doc_storage
import gmail_client
import qbo_client

MAX_BYTES = 25 * 1024 * 1024  # a PO/invoice PDF is ~100 KB; anything bigger is skipped

_META_COLS = (
    "id", "po_id", "invoice_id", "kind", "source", "filename", "mime_type",
    "byte_size", "content_hash", "captured_at", "captured_by",
)


class CaptureError(ValueError):
    """Bad request for a capture operation (missing thread, not configured, …).
    The API layer maps this to 404/422."""


# --------------------------------------------------------------------------- read


def _meta(row: dict) -> dict:
    out = dict(row)
    if out.get("captured_at") is not None and hasattr(out["captured_at"], "isoformat"):
        out["captured_at"] = out["captured_at"].isoformat()
    return out


def list_documents(conn, po_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {', '.join(_META_COLS)} FROM po_documents "
            "WHERE po_id = %s ORDER BY kind, captured_at DESC",
            (po_id,),
        )
        return [_meta(dict(r)) for r in cur.fetchall()]


def get_document_blob(conn, po_id: int, doc_id: int) -> tuple[str, str, bytes] | None:
    """(filename, mime_type, bytes) for one document, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT filename, mime_type, content, storage_path "
            "FROM po_documents WHERE id = %s AND po_id = %s",
            (doc_id, po_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    filename, mime_type, content, storage_path = row
    if content is not None:
        return filename, mime_type, bytes(content)
    if storage_path and doc_storage.is_enabled():
        return filename, mime_type, doc_storage.download(storage_path)
    return None


# -------------------------------------------------------------------------- write


def store_document(conn, po_id: int, *, kind: str, source: str, filename: str,
                   data: bytes, captured_by: str | None, invoice_id: int | None = None,
                   mime_type: str = "application/pdf") -> dict | None:
    """Insert one document, deduped on (po_id, kind, sha256). Returns the row's
    metadata dict, or None if an identical one was already stored."""
    digest = hashlib.sha256(data).hexdigest()

    storage_path = None
    inline: bytes | None = data
    if doc_storage.is_enabled():
        storage_path = f"po/{po_id}/{kind}/{digest}.pdf"
        doc_storage.upload(storage_path, data, mime_type)
        inline = None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO po_documents
                (po_id, invoice_id, kind, source, filename, mime_type, byte_size,
                 content_hash, content, storage_path, captured_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (po_id, kind, content_hash) DO NOTHING
            RETURNING """ + ", ".join(_META_COLS),
            (po_id, invoice_id, kind, source, filename, mime_type, len(data),
             digest, psycopg2.Binary(inline) if inline is not None else None,
             storage_path, captured_by),
        )
        row = cur.fetchone()
    return _meta(dict(row)) if row else None


def delete_document(conn, po_id: int, doc_id: int) -> dict:
    """Deletes one document (and its Storage object, if any). Returns
    {filename, kind}. Raises CaptureError if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM po_documents WHERE id = %s AND po_id = %s "
            "RETURNING filename, kind, storage_path",
            (doc_id, po_id),
        )
        gone = cur.fetchone()
    if gone is None:
        raise CaptureError("document not found")
    filename, kind, storage_path = gone
    if storage_path and doc_storage.is_enabled():
        try:
            doc_storage.delete(storage_path)
        except Exception:  # the row is gone; a stray object is not worth failing on
            pass
    return {"filename": filename, "kind": kind}


def capture_gmail(conn, po_id: int, *, client_id: str, client_secret: str,
                  captured_by: str | None) -> dict:
    """Pull every PDF attachment from the PO's Gmail thread.
    -> {stored: [...], skipped: [...], note: str}. Does not commit."""
    if not (client_id and client_secret):
        raise CaptureError("Gmail is not configured on this server")
    with conn.cursor() as cur:
        cur.execute("SELECT gmail_thread_id FROM purchase_orders WHERE id = %s", (po_id,))
        row = cur.fetchone()
    if row is None:
        raise CaptureError("PO not found")
    thread_id = row[0]
    if not thread_id:
        raise CaptureError("this PO has no Gmail thread (not ingested from email)")

    token = gmail_client.get_valid_access_token(conn, client_id, client_secret)
    thread = gmail_client.get_thread(token, thread_id)

    stored, skipped, seen = [], [], set()
    for msg in thread.get("messages", []):
        _body, atts = gmail_client.extract_body_and_attachments(msg)
        for att in atts:
            name = att.get("filename") or "attachment.pdf"
            try:
                data = gmail_client.attachment_bytes(token, msg["id"], att)
            except Exception as exc:
                skipped.append(f"{name}: {exc}")
                continue
            if not data or len(data) > MAX_BYTES:
                skipped.append(f"{name}: {len(data) if data else 0} bytes (skipped)")
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            rec = store_document(conn, po_id, kind="po_pdf", source="gmail",
                                 filename=name, data=data, captured_by=captured_by)
            (stored.append(rec) if rec else skipped.append(f"{name}: already captured"))

    note = (
        f"{len(stored)} PDF(s) captured from Gmail."
        if stored
        else "No new PDF attachments found in the thread."
    )
    return {"stored": stored, "skipped": skipped, "note": note}


def capture_qbo(conn, po_id: int, *, captured_by: str | None) -> dict:
    """Pull the rendered invoice PDF for each *confirmed* linked invoice.
    -> {stored, skipped, note}. Does not commit."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT 1 FROM purchase_orders WHERE id = %s", (po_id,))
        if cur.fetchone() is None:
            raise CaptureError("PO not found")
        cur.execute(
            """
            SELECT l.invoice_id, i.qbo_invoice_id, i.doc_number
            FROM po_invoice_links l JOIN qbo_invoices i ON i.id = l.invoice_id
            WHERE l.po_id = %s AND l.confirmed
            """,
            (po_id,),
        )
        links = [dict(r) for r in cur.fetchall()]
    if not links:
        raise CaptureError("no confirmed invoice link on this PO — link an invoice first")

    token, realm_id = qbo_client.get_valid_access_token(conn)
    stored, skipped = [], []
    for lk in links:
        label = lk["doc_number"] or lk["qbo_invoice_id"]
        try:
            data = qbo_client.fetch_invoice_pdf(token, realm_id, lk["qbo_invoice_id"])
        except Exception as exc:
            skipped.append(f"invoice {label}: {exc}")
            continue
        if not data or len(data) > MAX_BYTES:
            skipped.append(f"invoice {label}: {len(data) if data else 0} bytes (skipped)")
            continue
        rec = store_document(conn, po_id, kind="invoice_pdf", source="qbo",
                             filename=f"invoice-{label}.pdf", data=data,
                             captured_by=captured_by, invoice_id=lk["invoice_id"])
        (stored.append(rec) if rec else skipped.append(f"invoice {label}: already captured"))

    note = (
        f"{len(stored)} invoice PDF(s) captured from QuickBooks."
        if stored
        else "Nothing new — the linked invoice PDF(s) were already captured."
    )
    return {"stored": stored, "skipped": skipped, "note": note}


def store_upload(conn, po_id: int, *, filename: str, data: bytes, mime_type: str,
                 captured_by: str | None) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM purchase_orders WHERE id = %s", (po_id,))
        if cur.fetchone() is None:
            raise CaptureError("PO not found")
    if not data:
        raise CaptureError("empty file")
    if len(data) > MAX_BYTES:
        raise CaptureError(f"file is {len(data)} bytes — over the {MAX_BYTES} limit")
    rec = store_document(conn, po_id, kind="other", source="upload",
                         filename=filename or "upload.pdf", data=data,
                         captured_by=captured_by, mime_type=mime_type or "application/pdf")
    if rec is None:
        raise CaptureError("an identical file is already attached")
    return rec


# ----------------------------------------------------------------------- backfill

_NEEDS_GMAIL = """
    SELECT po.id FROM purchase_orders po
    WHERE po.gmail_thread_id IS NOT NULL AND po.status = 'active'
      AND NOT EXISTS (
        SELECT 1 FROM po_documents d WHERE d.po_id = po.id AND d.kind = 'po_pdf'
      )
    ORDER BY po.id DESC
"""

_NEEDS_QBO = """
    SELECT DISTINCT l.po_id FROM po_invoice_links l
    JOIN purchase_orders po ON po.id = l.po_id
    WHERE l.confirmed AND po.status = 'active'
      AND NOT EXISTS (
        SELECT 1 FROM po_documents d
        WHERE d.po_id = l.po_id AND d.kind = 'invoice_pdf' AND d.invoice_id = l.invoice_id
      )
    ORDER BY l.po_id DESC
"""


def _count(conn, sql: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM ({sql}) q")
        return cur.fetchone()[0]


def backfill(conn, *, sources: list[str], limit: int = 100,
             captured_by: str | None = "backfill",
             gmail_client_id: str = "", gmail_client_secret: str = "") -> dict:
    """Sweep POs that are missing their captured PDFs, up to `limit` per source.
    Commits after each PO, so a long run is resumable. Per-PO errors are collected,
    not fatal."""
    out: dict = {}

    if "gmail" in sources:
        res = {"scanned": 0, "captured": 0, "failed": 0, "errors": []}
        with conn.cursor() as cur:
            cur.execute(f"{_NEEDS_GMAIL} LIMIT %s", (limit,))
            ids = [r[0] for r in cur.fetchall()]
        for po_id in ids:
            res["scanned"] += 1
            try:
                r = capture_gmail(conn, po_id, client_id=gmail_client_id,
                                  client_secret=gmail_client_secret, captured_by=captured_by)
                conn.commit()
                res["captured"] += len(r["stored"])
            except Exception as exc:
                conn.rollback()
                res["failed"] += 1
                res["errors"].append(f"PO {po_id}: {exc}")
        res["remaining"] = _count(conn, _NEEDS_GMAIL)
        out["gmail"] = res

    if "qbo" in sources:
        res = {"scanned": 0, "captured": 0, "failed": 0, "errors": []}
        with conn.cursor() as cur:
            cur.execute(f"{_NEEDS_QBO} LIMIT %s", (limit,))
            ids = [r[0] for r in cur.fetchall()]
        for po_id in ids:
            res["scanned"] += 1
            try:
                r = capture_qbo(conn, po_id, captured_by=captured_by)
                conn.commit()
                res["captured"] += len(r["stored"])
            except Exception as exc:
                conn.rollback()
                res["failed"] += 1
                res["errors"].append(f"PO {po_id}: {exc}")
        res["remaining"] = _count(conn, _NEEDS_QBO)
        out["qbo"] = res

    return out
