"""GET / POST one purchase order for manual editing. Marks the row edited=TRUE so
the sync never overwrites it (same guard the Streamlit editor used)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, current_user
from ..reused_db import reused_conn
from ..services import po_admin, po_edit

router = APIRouter(prefix="/api/po", tags=["po-edit"])


class LineItemIn(BaseModel):
    product_raw: str | None = None
    product_name: str | None = None
    container_size: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    additional_cost: float | None = None
    sku: str | None = None
    is_sample: bool = False
    math_mismatch: str | None = None
    price_anomaly: str | None = None
    revision_status: str | None = None
    voided: bool = False
    void_reason: str | None = None


class HeaderIn(BaseModel):
    po_number: str | None = None
    customer_name: str | None = None
    po_date: str | None = None
    delivery_date: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    notes: str | None = None


class PoEditIn(BaseModel):
    header: HeaderIn
    items: list[LineItemIn]
    removed_items: list[LineItemIn] = []


@router.get("/{po_id}")
def get_po(po_id: int, _: AuthedUser = Depends(current_user)) -> dict:
    """Header + line items + removed_items, plus the admin extras (lifecycle
    status, revision chain, invoice links, audit trail)."""
    with reused_conn() as conn:
        po = po_admin.po_detail(conn, po_id)
    if po is None:
        raise HTTPException(404, "PO not found")
    return po


@router.post("/{po_id}")
def save_po(po_id: int, body: PoEditIn, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        failed, detail = po_edit.save_po_edit(
            conn,
            po_id,
            body.header.model_dump(),
            [it.model_dump() for it in body.items],
            [it.model_dump() for it in body.removed_items],
        )
    return {"ok": True, "math_check_failed": failed, "math_check_detail": detail}
