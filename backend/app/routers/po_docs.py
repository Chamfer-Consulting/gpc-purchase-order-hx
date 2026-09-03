"""Captured source documents for a PO — the emailed PO PDF (Gmail) and the
rendered invoice PDF (QuickBooks). See services/po_docs.py."""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_editor
from ..config import get_settings
from ..reused_db import reused_conn
from ..services import po_docs
from ..services.po_admin import AdminError

router = APIRouter(prefix="/api/po", tags=["po-docs"])


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AdminError as exc:
        msg = str(exc)
        raise HTTPException(404 if "not found" in msg else 422, msg) from exc


class CaptureIn(BaseModel):
    sources: list[str] = ["gmail", "qbo"]  # any of: gmail, qbo


class BackfillIn(BaseModel):
    sources: list[str] = ["gmail", "qbo"]
    limit: int = 100
    # the card drains the queue over several calls; True = a follow-up slice, so
    # only add an audit row if it actually captured / failed something.
    continued: bool = False


class UploadIn(BaseModel):
    filename: str
    content_b64: str
    mime_type: str = "application/pdf"


MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB — stored inline in po_documents.content
# (magic bytes -> canonical mime). Anything else is rejected.
_SNIFF = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_mime(data: bytes) -> str | None:
    for sig, mime in _SNIFF:
        if data.startswith(sig):
            return mime
    return None


@router.post("/documents/backfill")
def backfill(body: BackfillIn, user: AuthedUser = Depends(require_editor)) -> dict:
    """Sweep POs missing their captured PDFs, up to `limit` per source. Safe to
    re-run (sha256-deduped). The scheduled job (run_doc_capture.py) does the same
    on a timer."""
    s = get_settings()
    limit = max(1, min(body.limit, 1000))
    with reused_conn() as conn:
        out = po_docs.backfill(
            conn, sources=body.sources, limit=limit,
            captured_by=f"backfill:{_actor(user)}", actor=_actor(user),
            gmail_client_id=s.gmail_client_id, gmail_client_secret=s.gmail_client_secret,
            announce=not body.continued,
        )
    return {"ok": True, **out}


@router.get("/{po_id}/documents")
def list_documents(po_id: int, _: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return po_docs.list_documents(conn, po_id)


@router.get("/{po_id}/documents/{doc_id}")
def get_document(po_id: int, doc_id: int, _: AuthedUser = Depends(current_user)) -> Response:
    with reused_conn() as conn:
        doc = po_docs.get_document(conn, po_id, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    filename, mime_type, data = doc
    safe = (filename or "document.pdf").replace('"', "").replace("\n", " ").replace("\r", " ")
    return Response(
        content=data,
        media_type=mime_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}"'},
    )


@router.post("/{po_id}/documents/capture")
def capture(po_id: int, body: CaptureIn, user: AuthedUser = Depends(require_editor)) -> dict:
    s = get_settings()
    out: dict = {}
    with reused_conn() as conn:
        if "gmail" in body.sources:
            out["gmail"] = _guard(
                po_docs.capture_gmail, conn, po_id,
                client_id=s.gmail_client_id, client_secret=s.gmail_client_secret,
                captured_by=_actor(user),
            )
        if "qbo" in body.sources:
            out["qbo"] = _guard(
                po_docs.capture_qbo, conn, po_id, captured_by=_actor(user)
            )
    if not out:
        raise HTTPException(422, "no known source in 'sources' (use gmail and/or qbo)")
    return {"ok": True, **out}


@router.post("/{po_id}/documents/upload")
def upload(po_id: int, body: UploadIn, user: AuthedUser = Depends(require_editor)) -> dict:
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "content_b64 is not valid base64") from exc
    if not data:
        raise HTTPException(422, "empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file is {len(data) // 1024} KB; max is {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    sniffed = _sniff_mime(data)
    if sniffed is None:
        raise HTTPException(415, "only PDF and image files (PNG/JPEG/GIF) can be attached")
    with reused_conn() as conn:
        rec = _guard(
            po_docs.upload_document, conn, po_id,
            filename=body.filename, data=data, mime_type=sniffed,  # trust the bytes, not the caller
            captured_by=_actor(user),
        )
    return {"ok": True, "document": rec}


@router.delete("/{po_id}/documents/{doc_id}")
def delete_document(po_id: int, doc_id: int, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        _guard(po_docs.delete_document, conn, po_id, doc_id, _actor(user))
    return {"ok": True}
