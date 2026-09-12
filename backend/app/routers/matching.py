"""PO <-> invoice matching. Read + run over dashboard/qbo_matcher.py (reused
verbatim); confirm / reject go through services/matching.py, which adds an audit
row and a real 404 when the pair has no candidate link."""

import qbo_matcher  # shared/, via app.reuse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_editor
from ..cache import clear as clear_cache
from ..reused_db import reused_conn
from ..services import matching as matching_svc
from ..services.po_admin import AdminError

router = APIRouter(prefix="/api/matching", tags=["matching"])


class LinkRef(BaseModel):
    po_id: int
    invoice_id: int


class BatchIn(BaseModel):
    pairs: list[LinkRef]


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id


def _guard(fn, *args):
    try:
        return fn(*args)
    except AdminError as exc:
        msg = str(exc)
        raise HTTPException(404 if "no candidate link" in msg or "not found" in msg else 422, msg) from exc


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
def run(_: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        result = qbo_matcher.run_matching(conn)
    clear_cache()  # links moved -> Order Lifecycle / analytics revenue-by-match shift
    return result


@router.post("/confirm")
def confirm(ref: LinkRef, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        _guard(matching_svc.confirm, conn, _actor(user), ref.po_id, ref.invoice_id)
    clear_cache()
    return {"ok": True}


@router.post("/reject")
def reject(ref: LinkRef, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        _guard(matching_svc.reject, conn, _actor(user), ref.po_id, ref.invoice_id)
    clear_cache()
    return {"ok": True}


@router.post("/confirm-batch")
def confirm_batch(body: BatchIn, user: AuthedUser = Depends(require_editor)) -> dict:
    pairs = [(p.po_id, p.invoice_id) for p in body.pairs]
    with reused_conn() as conn:
        out = _guard(matching_svc.confirm_batch, conn, _actor(user), pairs)
    clear_cache()
    return {"ok": True, **out}
