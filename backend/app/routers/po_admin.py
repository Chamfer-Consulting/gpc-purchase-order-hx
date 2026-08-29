"""Admin CRUD endpoints for purchase orders — create, lifecycle status, soft
delete / restore, per-line void, revision regrouping, manual invoice linking, and
the audit trail. All mutations are audit-logged and stamp the PO edited = TRUE so
the extraction pipeline leaves it alone. See services/po_admin.py."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import AuthedUser, current_user
from ..reused_db import reused_conn
from ..services import audit, po_admin
from .po_edit import HeaderIn, LineItemIn

router = APIRouter(prefix="/api", tags=["po-admin"])


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id


# ------------------------------------------------------------------- request bodies


class NewPoIn(BaseModel):
    header: HeaderIn
    items: list[LineItemIn] = []


class StatusIn(BaseModel):
    status: str  # active | draft | cancelled | withdrawn | voided | deleted
    reason: str | None = None


class DeleteIn(BaseModel):
    reason: str | None = None


class VoidLineIn(BaseModel):
    voided: bool = True
    reason: str | None = None


class CustomerIn(BaseModel):
    customer_name: str | None = None
    customer_id: str | None = None


class RegroupIn(BaseModel):
    revision_of: str | None = None
    standalone: bool = False


class LinkIn(BaseModel):
    po_id: int
    invoice_id: int
    replace_existing: bool = False


def _guard(fn, *args):
    try:
        return fn(*args)
    except po_admin.AdminError as exc:
        msg = str(exc)
        raise HTTPException(404 if "not found" in msg else 422, msg) from exc


# -------------------------------------------------------------------------- routes


@router.post("/po")
def create_po(body: NewPoIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        po_id = _guard(
            po_admin.create_po, conn, _actor(user),
            body.header.model_dump(), [it.model_dump() for it in body.items],
        )
        detail = po_admin.po_detail(conn, po_id)
    return {"ok": True, "po_id": po_id, "detail": detail}


@router.get("/po/{po_id}/detail")
def po_detail(po_id: int, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        detail = po_admin.po_detail(conn, po_id)
    if detail is None:
        raise HTTPException(404, "PO not found")
    return detail


@router.get("/po/{po_id}/audit")
def po_audit(po_id: int, _: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return audit.history(conn, "purchase_order", po_id)


@router.post("/po/{po_id}/status")
def set_status(po_id: int, body: StatusIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        after = _guard(po_admin.set_status, conn, _actor(user), po_id, body.status, body.reason)
    return {"ok": True, "header": after}


@router.delete("/po/{po_id}")
def soft_delete(po_id: int, body: DeleteIn | None = None,
                user: AuthedUser = Depends(current_user)) -> dict:
    reason = body.reason if body else None
    with reused_conn() as conn:
        after = _guard(po_admin.set_status, conn, _actor(user), po_id, "deleted", reason)
    return {"ok": True, "header": after}


@router.post("/po/{po_id}/restore")
def restore(po_id: int, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        after = _guard(po_admin.set_status, conn, _actor(user), po_id, "active", None)
    return {"ok": True, "header": after}


@router.post("/po/{po_id}/line/{line_id}/void")
def void_line(po_id: int, line_id: int, body: VoidLineIn,
              user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        row = _guard(po_admin.void_line, conn, _actor(user), po_id, line_id,
                     body.voided, body.reason)
    return {"ok": True, "line": row}


@router.post("/po/{po_id}/customer")
def set_customer(po_id: int, body: CustomerIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        after = _guard(po_admin.set_customer, conn, _actor(user), po_id,
                       body.customer_name, body.customer_id)
    return {"ok": True, "header": after}


@router.post("/po/{po_id}/regroup")
def regroup(po_id: int, body: RegroupIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        out = _guard(po_admin.regroup, conn, _actor(user), po_id,
                     body.revision_of, body.standalone)
    return {"ok": True, **out}


@router.get("/invoices")
def search_invoices(
    search: str | None = Query(None),
    limit: int = Query(25, le=100),
    _: AuthedUser = Depends(current_user),
) -> list[dict]:
    with reused_conn() as conn:
        return po_admin.search_invoices(conn, search, limit)


@router.post("/links")
def create_link(body: LinkIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        links = _guard(po_admin.link_invoice, conn, _actor(user), body.po_id,
                       body.invoice_id, body.replace_existing)
    return {"ok": True, "links": links}


@router.delete("/links")
def delete_link(
    po_id: int = Query(...),
    invoice_id: int = Query(...),
    user: AuthedUser = Depends(current_user),
) -> dict:
    with reused_conn() as conn:
        links = _guard(po_admin.unlink_invoice, conn, _actor(user), po_id, invoice_id)
    return {"ok": True, "links": links}
