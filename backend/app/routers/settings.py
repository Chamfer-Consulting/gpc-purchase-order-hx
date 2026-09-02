"""Settings — product visibility and saved views. See services/settings.py.
(OAuth connections live in routers/connections.py; the doc-backfill card calls
routers/po_docs.py.)"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, clear_role_cache, current_user, require_admin, require_editor
from ..cache import clear as clear_cache
from ..reused_db import reused_conn
from ..services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])


class HideIn(BaseModel):
    name: str
    hidden: bool


class ViewIn(BaseModel):
    kind: str
    name: str
    config: dict[str, Any] = {}


class ViewDeleteIn(BaseModel):
    kind: str
    name: str


def _owner(user: AuthedUser) -> str:
    return user.email or user.id


@router.get("/hidden-products")
def hidden_products(_: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return svc.list_products(conn)


@router.post("/hidden-products")
def set_hidden(body: HideIn, _: AuthedUser = Depends(require_editor)) -> dict:
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    with reused_conn() as conn:
        svc.set_product_hidden(conn, body.name, body.hidden)
    clear_cache()  # analytics pages are cached by filter params only — rebuild them
    return {"ok": True}


@router.get("/hidden-customers")
def hidden_customers(_: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return svc.list_customers(conn)


@router.post("/hidden-customers")
def set_customer_hidden(body: HideIn, _: AuthedUser = Depends(require_editor)) -> dict:
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    with reused_conn() as conn:
        svc.set_customer_hidden(conn, body.name, body.hidden)
    clear_cache()
    return {"ok": True}


class HideInvoiceIn(BaseModel):
    qbo_invoice_id: str
    hidden: bool
    reason: str | None = None


@router.get("/hidden-invoices")
def hidden_invoices(_: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return svc.list_hidden_invoices(conn)


@router.post("/hidden-invoices")
def set_invoice_hidden(body: HideInvoiceIn, _: AuthedUser = Depends(require_editor)) -> dict:
    if not body.qbo_invoice_id.strip():
        raise HTTPException(422, "qbo_invoice_id is required")
    with reused_conn() as conn:
        svc.set_invoice_hidden(conn, body.qbo_invoice_id.strip(), body.hidden,
                               (body.reason or "").strip() or None)
    clear_cache()  # excludes/restores the invoice from every analytics page
    return {"ok": True}


# --- team / access control (admin only) --------------------------------


class TeamMemberIn(BaseModel):
    email: str
    role: str  # viewer | editor | admin
    note: str | None = None


@router.get("/team")
def list_team(_: AuthedUser = Depends(require_admin)) -> list[dict]:
    with reused_conn() as conn:
        return svc.list_team(conn)


@router.post("/team")
def set_team_member(body: TeamMemberIn, user: AuthedUser = Depends(require_admin)) -> dict:
    try:
        with reused_conn() as conn:
            svc.set_team_member(conn, _owner(user), body.email, body.role, body.note)
    except svc.TeamError as e:
        raise HTTPException(422, str(e))
    clear_role_cache(body.email)
    return {"ok": True}


@router.delete("/team/{email}")
def remove_team_member(email: str, user: AuthedUser = Depends(require_admin)) -> dict:
    if email.strip().lower() == (user.email or "").strip().lower():
        raise HTTPException(422, "you can't remove your own access")
    try:
        with reused_conn() as conn:
            svc.remove_team_member(conn, _owner(user), email)
    except svc.TeamError as e:
        raise HTTPException(422, str(e))
    clear_role_cache(email)
    return {"ok": True}


@router.get("/views")
def list_views(kind: str, user: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return svc.list_views(conn, kind, _owner(user))


@router.post("/views")
def save_view(body: ViewIn, user: AuthedUser = Depends(require_editor)) -> dict:
    if not body.name.strip() or not body.kind.strip():
        raise HTTPException(422, "name and kind are required")
    with reused_conn() as conn:
        svc.save_view(conn, body.kind, body.name.strip(), body.config, _owner(user))
    return {"ok": True}


@router.delete("/views")
def delete_view(body: ViewDeleteIn, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        svc.delete_view(conn, body.kind, body.name, _owner(user))
    return {"ok": True}
