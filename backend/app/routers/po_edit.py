"""GET / POST one purchase order for manual editing. Marks the row edited=TRUE so
the sync never overwrites it (same guard the Streamlit editor used)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_editor, require_viewer
from ..reused_db import reused_conn
from ..services import po_admin, po_edit

router = APIRouter(prefix="/api/po", tags=["po-edit"], dependencies=[Depends(require_viewer)])


class LineItemIn(BaseModel):
    # The existing line_items.id, when the client is editing a row it loaded (vs.
    # a row it added). save_po_edit() diffs by this id — UPDATE the rows that
    # carry a known id, INSERT the ones that don't, DELETE the ones that vanished
    # — so line_items.id stays stable and per-line state (math_ack, void_reason,
    # price_anomaly) survives an edit. Without this field Pydantic dropped the id
    # the SPA already sends, so *every* save silently deleted and re-inserted
    # every line (fresh ids each time) — which then made the just-saved form's
    # rows look "changed on the server" on the post-save refetch and lit a false
    # concurrency-conflict banner.
    id: int | None = None
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
    # optimistic-concurrency: the lock_version the client loaded. Omit to skip the
    # check (old clients); mismatch -> 409 stale_write.
    expected_version: int | None = None


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
def save_po(po_id: int, body: PoEditIn, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        result = po_edit.save_po_edit(
            conn,
            po_id,
            body.header.model_dump(),
            [it.model_dump() for it in body.items],
            [it.model_dump() for it in body.removed_items],
            actor=user.email or user.id,
            expected_version=body.expected_version,
        )
    return {"ok": True, **result}
