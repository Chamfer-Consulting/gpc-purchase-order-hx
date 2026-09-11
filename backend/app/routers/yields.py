"""Product Yields — harvest logging. A domain separate from PO/QBO sales; see
services/yields.py. No router-level role floor: 'field' (the harvest kiosk
role) is rank 0, the floor of the whole app, so bare `current_user` is already
correct for reads/submissions. Product management stays `require_editor`,
matching the rest of the app's catalog-editing endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import AuthedUser, app_role, current_user, require_editor
from ..reused_db import reused_conn
from ..services import yields as yields_svc

router = APIRouter(prefix="/api/yields", tags=["yields"])


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id


# --- products ----------------------------------------------------------------


class ProductIn(BaseModel):
    name: str
    notes: str | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.get("/products")
def list_products(include_inactive: bool = False, _: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return yields_svc.list_products(conn, include_inactive=include_inactive)


@router.post("/products")
def create_product(body: ProductIn, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        return yields_svc.create_product(conn, body.name, body.notes, actor=_actor(user))


@router.post("/products/{product_id}")
def update_product(product_id: int, body: ProductPatch, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        return yields_svc.update_product(
            conn, product_id, name=body.name, active=body.active, notes=body.notes, actor=_actor(user),
        )


# --- entries -----------------------------------------------------------------


class EntryIn(BaseModel):
    yield_product_id: int
    harvest_date: date
    weight: float
    unit: str = "oz"
    tray_count: int = 0
    discarded_tray_count: int = 0
    storage_bin: str | None = None
    lot_code: str | None = None
    harvested_by: str
    notes: str | None = None


class EntryPatch(BaseModel):
    weight: float | None = None
    unit: str | None = None
    tray_count: int | None = None
    discarded_tray_count: int | None = None
    storage_bin: str | None = None
    lot_code: str | None = None
    harvested_by: str | None = None
    notes: str | None = None
    harvest_date: date | None = None


class VoidIn(BaseModel):
    reason: str | None = None


@router.post("/entries")
def create_entry(body: EntryIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return yields_svc.create_entry(
            conn,
            yield_product_id=body.yield_product_id,
            harvest_date=body.harvest_date,
            weight=body.weight,
            unit=body.unit,
            tray_count=body.tray_count,
            discarded_tray_count=body.discarded_tray_count,
            storage_bin=body.storage_bin,
            lot_code=body.lot_code,
            harvested_by=body.harvested_by,
            notes=body.notes,
            submitted_by=_actor(user) or "",
        )


@router.get("/entries")
def list_entries(
    yield_product_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    harvested_by: str | None = None,
    submitted_by: str | None = None,
    include_voided: bool = False,
    _: AuthedUser = Depends(current_user),
) -> list[dict]:
    with reused_conn() as conn:
        return yields_svc.list_entries(
            conn,
            yield_product_id=yield_product_id,
            date_from=date_from,
            date_to=date_to,
            harvested_by=harvested_by,
            submitted_by=submitted_by,
            include_voided=include_voided,
        )


@router.post("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryPatch, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return yields_svc.update_entry(
            conn, entry_id, body.model_dump(exclude_unset=True),
            actor=_actor(user), actor_role=app_role(user.email),
        )


@router.post("/entries/{entry_id}/void")
def void_entry(entry_id: int, body: VoidIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return yields_svc.void_entry(
            conn, entry_id, body.reason, actor=_actor(user), actor_role=app_role(user.email),
        )


# --- notes -------------------------------------------------------------------


class NoteIn(BaseModel):
    yield_product_id: int | None = None
    note: str
    note_date: date | None = None


@router.get("/notes")
def list_notes(yield_product_id: int | None = None, _: AuthedUser = Depends(current_user)) -> list[dict]:
    with reused_conn() as conn:
        return yields_svc.list_notes(conn, yield_product_id=yield_product_id)


@router.post("/notes")
def create_note(body: NoteIn, user: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return yields_svc.create_note(
            conn,
            yield_product_id=body.yield_product_id,
            note=body.note,
            note_date=body.note_date,
            submitted_by=_actor(user) or "",
        )


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        yields_svc.delete_note(conn, note_id, actor=_actor(user))
    return {"ok": True}
