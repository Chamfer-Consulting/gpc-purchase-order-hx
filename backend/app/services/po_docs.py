"""Capture and serve the source PDFs behind a purchase order:

  * po_pdf       — the PDF attachment(s) on the PO's Gmail thread
  * invoice_pdf  — the rendered invoice PDF for every confirmed linked invoice,
    pulled from QuickBooks' Print / Save-as-PDF endpoint
  * other        — a file attached by hand through the app

(A text-only Gmail thread has no PDF to capture — the "open email thread" deep
link on the PO covers that case.)

Bytes are stored inline in po_documents.content (PDFs are small). Dedupe is by
sha256 within (po_id, kind). All capture / delete calls are audit-logged."""

import hashlib

import psycopg2
import psycopg2.extras

import gmail_client  # repo root, via app.reuse
import qbo_client  # dashboard/, via app.reuse

from . import audit
from .po_admin import AdminError

_MAX_BYTES = 25 * 1024 * 1024  # skip anything larger — a PO/invoice PDF is ~100 KB

_META_COLS = (
    "id", "po_id", "invoice_id", "kind", "source", "filename", "mime_type",
    "byte_size", "content_hash", "captured_at", "captured_by",
)


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


def get_document(conn, po_id: int, doc_id: int) -> tuple[str, str, bytes] | None:
    """(filename, mime_type, bytes) for one document, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT filename, mime_type, content FROM po_documents WHERE id = %s AND po_id = %s",
            (doc_id, po_id),
        )
        row = cur.fetchone()
    if row is None or row[2] is None:
        return None
    return row[0], row[1], bytes(row[2])


# -------------------------------------------------------------------------- write


def _store(conn, po_id: int, *, kind: str, source: str, filename: str, data: bytes,
           captured_by: str | None, invoice_id: int | None = None,
           mime_type: str = "application/pdf") -> dict | None:
    """Insert one document, deduped on (po_id, kind, sha256). Returns the row's
    metadata dict, or None if an identical one was already stored."""
    digest = hashlib.sha256(data).hexdigest()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO po_documents
                (po_id, invoice_id, kind, source, filename, mime_type, byte_size,
                 content_hash, content, captured_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (po_id, kind, content_hash) DO NOTHING
            RETURNING """ + ", ".join(_META_COLS),
            (po_id, invoice_id, kind, source, filename, mime_type, len(data),
             digest, psycopg2.Binary(data), captured_by),
        )
        row = cur.fetchone()
    return _meta(dict(row)) if row else None


def capture_gmail(conn, po_id: int, *, client_id: str, client_secret: str,
                  captured_by: str | None) -> dict:
    """Pull every PDF attachment from the PO's Gmail thread. Returns
    {stored: [...], skipped: [...], note: str}."""
    if not (client_id and client_secret):
        raise AdminError("Gmail is not configured on this server")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gmail_thread_id, source_file FROM purchase_orders WHERE id = %s", (po_id,)
        )
        row = cur.fetchone()
    if row is None:
        raise AdminError("PO not found")
    thread_id = row[0]
    if not thread_id:
        raise AdminError("this PO has no Gmail thread (not ingested from email)")

    token = gmail_client.get_valid_access_token(conn, client_id, client_secret)
    thread = gmail_client.get_thread(token, thread_id)

    stored, skipped, seen = [], [], set()
    for msg in thread.get("messages", []):
        _body, atts = gmail_client.extract_body_and_attachments(msg)
        for att in atts:
            name = att.get("filename") or "attachment.pdf"
            try:
                data = gmail_client.attachment_bytes(token, msg["id"], att)
            except Exception as exc:  # one bad part shouldn't sink the whole capture
                skipped.append(f"{name}: {exc}")
                continue
            if not data or len(data) > _MAX_BYTES:
                skipped.append(f"{name}: {len(data) if data else 0} bytes (skipped)")
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            rec = _store(conn, po_id, kind="po_pdf", source="gmail", filename=name,
                         data=data, captured_by=captured_by)
            (stored.append(rec) if rec else skipped.append(f"{name}: already captured"))

    audit.log(conn, actor=captured_by, action="doc_capture", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"source": "gmail", "thread_id": thread_id,
                     "stored": [r["filename"] for r in stored]})
    conn.commit()
    note = (
        f"{len(stored)} PDF(s) captured from Gmail."
        if stored
        else "No new PDF attachments found in the thread."
    )
    return {"stored": stored, "skipped": skipped, "note": note}


def capture_qbo(conn, po_id: int, *, captured_by: str | None) -> dict:
    """Pull the rendered invoice PDF for each *confirmed* linked invoice."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT 1 FROM purchase_orders WHERE id = %s", (po_id,))
        if cur.fetchone() is None:
            raise AdminError("PO not found")
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
        raise AdminError("no confirmed invoice link on this PO — link an invoice first")

    token, realm_id = qbo_client.get_valid_access_token(conn)
    stored, skipped = [], []
    for lk in links:
        label = lk["doc_number"] or lk["qbo_invoice_id"]
        try:
            data = qbo_client.fetch_invoice_pdf(token, realm_id, lk["qbo_invoice_id"])
        except Exception as exc:
            skipped.append(f"invoice {label}: {exc}")
            continue
        if not data or len(data) > _MAX_BYTES:
            skipped.append(f"invoice {label}: {len(data) if data else 0} bytes (skipped)")
            continue
        rec = _store(conn, po_id, kind="invoice_pdf", source="qbo",
                     filename=f"invoice-{label}.pdf", data=data,
                     captured_by=captured_by, invoice_id=lk["invoice_id"])
        (stored.append(rec) if rec else skipped.append(f"invoice {label}: already captured"))

    audit.log(conn, actor=captured_by, action="doc_capture", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"source": "qbo", "invoices": [lk["doc_number"] for lk in links],
                     "stored": [r["filename"] for r in stored]})
    conn.commit()
    note = (
        f"{len(stored)} invoice PDF(s) captured from QuickBooks."
        if stored
        else "Nothing new — the linked invoice PDF(s) were already captured."
    )
    return {"stored": stored, "skipped": skipped, "note": note}


def upload_document(conn, po_id: int, *, filename: str, data: bytes,
                    mime_type: str, captured_by: str | None) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM purchase_orders WHERE id = %s", (po_id,))
        if cur.fetchone() is None:
            raise AdminError("PO not found")
    if not data:
        raise AdminError("empty file")
    if len(data) > _MAX_BYTES:
        raise AdminError(f"file is {len(data)} bytes — over the {_MAX_BYTES} limit")
    rec = _store(conn, po_id, kind="other", source="upload", filename=filename or "upload.pdf",
                 data=data, captured_by=captured_by, mime_type=mime_type or "application/pdf")
    audit.log(conn, actor=captured_by, action="doc_upload", entity="purchase_order",
              entity_id=po_id, before=None, after={"filename": filename})
    conn.commit()
    if rec is None:
        raise AdminError("an identical file is already attached")
    return rec


def delete_document(conn, po_id: int, doc_id: int, actor: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM po_documents WHERE id = %s AND po_id = %s RETURNING filename, kind",
            (doc_id, po_id),
        )
        gone = cur.fetchone()
        if gone is None:
            raise AdminError("document not found")
        audit.log(conn, actor=actor, action="doc_delete", entity="purchase_order",
                  entity_id=po_id, before={"filename": gone[0], "kind": gone[1]}, after=None)
    conn.commit()
