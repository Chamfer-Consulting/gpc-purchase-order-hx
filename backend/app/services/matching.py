"""Confirm / reject a PO<->invoice link, with an audit row and a real 404 when the
pair has no link. The link-state SQL lives in shared/qbo_matcher.py; this adds the
`actor` + audit + single-commit wrapper the router needs (mirrors how
services/po_admin.link_invoice wraps qbo_matcher.manual_link)."""

import qbo_matcher  # shared/, via app.reuse

from . import audit
from .po_admin import AdminError


def _confirm_link(conn, po_id: int, invoice_id: int) -> bool:
    """qbo_matcher.confirm_link, with InvoiceAlreadyLinked turned into the same
    typed AdminError every other admin-surface rejection uses — a one-click Confirm
    must never silently give one invoice two confirmed POs (see InvoiceAlreadyLinked)."""
    try:
        return qbo_matcher.confirm_link(conn, po_id, invoice_id, commit=False)
    except qbo_matcher.InvoiceAlreadyLinked as exc:
        raise AdminError(str(exc)) from exc


def confirm(conn, actor: str | None, po_id: int, invoice_id: int) -> None:
    hit = _confirm_link(conn, po_id, invoice_id)
    if not hit:
        raise AdminError("no candidate link for that PO / invoice")
    audit.log(conn, actor=actor, action="link_confirm", entity="purchase_order",
              entity_id=po_id, before=None, after={"invoice_id": invoice_id})
    conn.commit()


def reject(conn, actor: str | None, po_id: int, invoice_id: int) -> None:
    hit = qbo_matcher.reject_link(conn, po_id, invoice_id, commit=False)
    if not hit:
        raise AdminError("no candidate link for that PO / invoice")
    audit.log(conn, actor=actor, action="link_reject", entity="purchase_order",
              entity_id=po_id, before=None, after={"invoice_id": invoice_id})
    conn.commit()


def confirm_batch(conn, actor: str | None, pairs: list[tuple[int, int]]) -> dict:
    """Atomic multi-confirm for the reconcile screen's 'confirm all high-confidence'.
    Every pair must have a link row; if any doesn't, nothing is committed."""
    seen: list[tuple[int, int]] = list(dict.fromkeys(pairs))
    missing: list[dict] = []
    for po_id, invoice_id in seen:
        if not _confirm_link(conn, po_id, invoice_id):
            missing.append({"po_id": po_id, "invoice_id": invoice_id})
    if missing:
        raise AdminError(f"{len(missing)} pair(s) had no candidate link; nothing confirmed")
    for po_id, invoice_id in seen:
        audit.log(conn, actor=actor, action="link_confirm", entity="purchase_order",
                  entity_id=po_id, before=None, after={"invoice_id": invoice_id, "batch": True})
    conn.commit()
    return {"confirmed": [{"po_id": p, "invoice_id": i} for p, i in seen]}
