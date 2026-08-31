"""Settings — product visibility and saved views. See services/settings.py.
(OAuth connections live in routers/connections.py; the doc-backfill card calls
routers/po_docs.py.)"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_editor
from ..reused_db import reused_conn
from ..services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])


class HideIn(BaseModel):
    product_name: str
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
    if not body.product_name.strip():
        raise HTTPException(422, "product_name is required")
    with reused_conn() as conn:
        svc.set_product_hidden(conn, body.product_name, body.hidden)
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
