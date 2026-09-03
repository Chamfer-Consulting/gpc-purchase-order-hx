"""API-layer wrapper around po_doc_capture (repo root). Adds the audit-log row and
translates po_doc_capture.CaptureError -> po_admin.AdminError so the routers'
existing _guard() maps it to 404/422. The scheduled runner (run_doc_capture.py)
calls po_doc_capture directly and doesn't go through here."""

import po_doc_capture as core  # repo root, via app.reuse

from . import audit
from .po_admin import AdminError

# re-exports the routers use
list_documents = core.list_documents
get_document = core.get_document_blob


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except core.CaptureError as exc:
        raise AdminError(str(exc)) from exc


def capture_gmail(conn, po_id: int, *, client_id: str, client_secret: str,
                  captured_by: str | None) -> dict:
    result = _wrap(core.capture_gmail, conn, po_id, client_id=client_id,
                   client_secret=client_secret, captured_by=captured_by)
    audit.log(conn, actor=captured_by, action="doc_capture", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"source": "gmail", "stored": [r["filename"] for r in result["stored"]],
                     # `note` lands in the /audit "Why" column via audit.derive_reason
                     "note": result.get("note")})
    conn.commit()
    return result


def capture_qbo(conn, po_id: int, *, captured_by: str | None) -> dict:
    result = _wrap(core.capture_qbo, conn, po_id, captured_by=captured_by)
    audit.log(conn, actor=captured_by, action="doc_capture", entity="purchase_order",
              entity_id=po_id, before=None,
              after={"source": "qbo", "stored": [r["filename"] for r in result["stored"]],
                     "note": result.get("note")})
    conn.commit()
    return result


def upload_document(conn, po_id: int, *, filename: str, data: bytes, mime_type: str,
                    captured_by: str | None) -> dict:
    rec = _wrap(core.store_upload, conn, po_id, filename=filename, data=data,
                mime_type=mime_type, captured_by=captured_by)
    audit.log(conn, actor=captured_by, action="doc_upload", entity="purchase_order",
              entity_id=po_id, before=None, after={"filename": filename})
    conn.commit()
    return rec


def delete_document(conn, po_id: int, doc_id: int, actor: str | None) -> None:
    gone = _wrap(core.delete_document, conn, po_id, doc_id)
    audit.log(conn, actor=actor, action="doc_delete", entity="purchase_order",
              entity_id=po_id, before=gone, after=None)
    conn.commit()


def backfill(conn, *, sources: list[str], limit: int, captured_by: str | None,
             gmail_client_id: str, gmail_client_secret: str,
             actor: str | None = None, max_seconds: float | None = 18.0) -> dict:
    out = core.backfill(conn, sources=sources, limit=limit, captured_by=captured_by,
                        gmail_client_id=gmail_client_id,
                        gmail_client_secret=gmail_client_secret, max_seconds=max_seconds)
    # Audit the sweep — the per-PO capture_* helpers above log individually, but
    # core.backfill calls the plain po_doc_capture functions, so without this a
    # Settings → Document capture run leaves no trace in /audit. The card drives
    # this in a loop (one HTTP call can't outrun the request timeout), so only
    # log a slice that actually did something — skip the no-op tail calls.
    # (The scheduled runner reports separately, via pipeline_summary.)
    buckets = {k: v for k, v in out.items() if k in ("gmail", "qbo")}
    if any(b["captured"] or b["failed"] for b in buckets.values()):
        parts = [
            f"{src}: {b['captured']}/{b['scanned']} captured"
            + (f", {b['failed']} failed" if b.get("failed") else "")
            + (f", {b['remaining']} still to do" if b.get("remaining") else "")
            for src, b in buckets.items()
        ]

        def _trim(b: dict) -> dict:
            errs = b.get("errors") or []
            return {**b, "errors": errs[:10],
                    **({"errors_truncated": len(errs) - 10} if len(errs) > 10 else {})}

        audit.log(
            conn, actor=actor or captured_by, action="doc_backfill", entity="po_documents",
            entity_id=None, before=None,
            after={"sources": sources, "note": " · ".join(parts),
                   **{k: _trim(v) for k, v in buckets.items()}},
        )
        conn.commit()
    return out
