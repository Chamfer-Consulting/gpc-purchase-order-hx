"""The unified /reconcile screen's backend: one queue, one per-PO view. Reads
only — the mutations reuse the existing po / matching / review endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import AuthedUser, current_user
from ..reused_db import reused_conn
from ..services import reconcile

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])


@router.get("/queue")
def queue(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return reconcile.queue(conn)


@router.get("/po/{po_id}")
def po_view(po_id: int, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        view = reconcile.po_view(conn, po_id)
    if view is None:
        raise HTTPException(404, "PO not found")
    return view
