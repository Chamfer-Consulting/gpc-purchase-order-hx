"""PO <-> invoice matching. Thin wrappers over dashboard/qbo_matcher.py (reused
verbatim), on psycopg2 connections."""

import qbo_matcher  # dashboard/, via app.reuse
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import AuthedUser, current_user
from ..reused_db import reused_conn

router = APIRouter(prefix="/api/matching", tags=["matching"])


class LinkRef(BaseModel):
    po_id: int
    invoice_id: int


@router.get("/review")
def review(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        candidates = qbo_matcher.get_needs_review(conn)
        po_ids = sorted({c["po_id"] for c in candidates})
        inv_ids = sorted({c["invoice_id"] for c in candidates})
        po_items, inv_items = qbo_matcher.get_line_items_for_review(conn, po_ids, inv_ids)
        unlinked = qbo_matcher.get_unlinked_pos(conn)
    return {
        "candidates": candidates,
        "po_items": {str(k): v for k, v in po_items.items()},
        "inv_items": {str(k): v for k, v in inv_items.items()},
        "unlinked": unlinked,
    }


@router.post("/run")
def run(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return qbo_matcher.run_matching(conn)


@router.post("/confirm")
def confirm(ref: LinkRef, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        qbo_matcher.confirm_link(conn, ref.po_id, ref.invoice_id)
    return {"ok": True}


@router.post("/reject")
def reject(ref: LinkRef, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        qbo_matcher.reject_link(conn, ref.po_id, ref.invoice_id)
    return {"ok": True}
