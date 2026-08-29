"""Captured source documents for a PO — the emailed PO PDF (Gmail) and the
rendered invoice PDF (QuickBooks). See services/po_docs.py."""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import AuthedUser, current_user
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


class UploadIn(BaseModel):
    filename: str
    content_b64: str
    mime_type: str = "application/pdf"


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
def capture(po_id: int, body: CaptureIn, user: AuthedUser = Depends(current_user)) -> dict:
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
def upload(po_id: int, body: UploadIn, user: AuthedUser = Depends(current_user)) -> dict:
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "content_b64 is not valid base64") from exc
    with reused_conn() as conn:
        rec = _guard(
            po_docs.upload_document, conn, po_id,
            filename=body.filename, data=data, mime_type=body.mime_type,
            captured_by=_actor(user),
        )
    return {"ok": True, "document": rec}


@router.delete("/{po_id}/documents/{doc_id}")
def delete_document(po_id: int, doc_id: int, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        _guard(po_docs.delete_document, conn, po_id, doc_id, _actor(user))
    return {"ok": True}
