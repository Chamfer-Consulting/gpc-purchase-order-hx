"""Read + manual-edit one purchase order. Ported from dashboard/data.py:save_po_edit
(plain SQL + math_check.validate_math, no pandas) so the Edit PO page works now.

save_po_edit is the primary edit path. It:
  * row-locks the PO (FOR UPDATE) and checks the client's expected_version
    (optimistic concurrency -> StaleWrite / HTTP 409),
  * refuses to edit a non-active PO (NotActive / HTTP 409),
  * diffs line items by id (UPDATE kept rows in place, INSERT new, DELETE gone) —
    no DELETE-all + re-INSERT, so line_items.id stays stable and there is no
    zero-line window for a concurrent reader,
  * writes an audit_log row and stamps edited / edited_by / edited_at, and
  * bumps lock_version by 1.
"""

import psycopg2.extras

from math_check import validate_math  # repo root, via app.reuse

from ..errors import NotActive, NotFound, StaleWrite
from . import audit

_HEADER_COLS = (
    "id", "source_file", "po_number", "po_date", "delivery_date", "sent_date",
    "customer_name", "customer_id", "subtotal", "tax", "total", "notes",
    "math_check_failed", "math_check_detail", "edited", "edited_at", "edited_by",
    "lock_version", "gmail_thread_id",
)
_ITEM_COLS = (
    "id", "product_raw", "product_name", "container_size", "quantity", "unit_price",
    "line_total", "additional_cost", "sku", "is_sample", "math_mismatch",
    "price_anomaly", "revision_status", "is_removed", "voided", "void_reason",
)
# math_mismatch is recomputed by validate_math (it mutates the item dicts in place
# for non-voided lines); price_anomaly is pipeline-owned. _update_line never writes
# either column, so an edit preserves the DB value; _insert_line takes the fresh
# math_mismatch and leaves price_anomaly for the next sync to re-evaluate.


def _jsonify(row: dict) -> dict:
    for k, v in list(row.items()):
        if hasattr(v, "isoformat"):
            row[k] = v.isoformat()
        elif isinstance(v, (bytes, memoryview)):
            row[k] = None
        else:
            try:
                from decimal import Decimal

                if isinstance(v, Decimal):
                    row[k] = float(v)
            except Exception:
                pass
    return row


def get_po(conn, po_id: int) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {', '.join(_HEADER_COLS)} FROM purchase_orders WHERE id = %s", (po_id,)
        )
        header = cur.fetchone()
        if header is None:
            return None
        cur.execute(
            f"SELECT {', '.join(_ITEM_COLS)} FROM line_items WHERE po_id = %s ORDER BY is_removed, id",
            (po_id,),
        )
        items = [dict(r) for r in cur.fetchall()]
    return {
        "header": _jsonify(dict(header)),
        "items": [_jsonify(dict(it)) for it in items if not it["is_removed"]],
        "removed_items": [_jsonify(dict(it)) for it in items if it["is_removed"]],
    }


def _line_params(po_id: int, it: dict, *, removed: bool) -> dict:
    return {
        "po_id": po_id,
        "product_raw": it.get("product_raw") or it.get("product_name"),
        "product_name": it.get("product_name"),
        "container_size": it.get("container_size"),
        "quantity": it.get("quantity"),
        "unit_price": it.get("unit_price"),
        "line_total": it.get("line_total"),
        "additional_cost": it.get("additional_cost"),
        "sku": it.get("sku"),
        "is_sample": bool(it.get("is_sample", False)),
        "math_mismatch": it.get("math_mismatch") if not it.get("voided") else None,
        "price_anomaly": None,
        "revision_status": it.get("revision_status") or ("Removed" if removed else "Edited"),
        "is_removed": removed,
        "voided": bool(it.get("voided", False)),
        "void_reason": it.get("void_reason") if it.get("voided") else None,
    }


def _insert_line(cur, po_id: int, it: dict, *, removed: bool) -> None:
    cur.execute(
        """
        INSERT INTO line_items (
            po_id, product_raw, product_name, container_size,
            quantity, unit_price, line_total, additional_cost, sku, is_sample,
            math_mismatch, price_anomaly, revision_status, is_removed, voided, void_reason
        ) VALUES (
            %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
            %(quantity)s, %(unit_price)s, %(line_total)s, %(additional_cost)s, %(sku)s, %(is_sample)s,
            %(math_mismatch)s, %(price_anomaly)s, %(revision_status)s, %(is_removed)s,
            %(voided)s, %(void_reason)s
        )
        """,
        _line_params(po_id, it, removed=removed),
    )


def _update_line(cur, po_id: int, line_id: int, it: dict, *, removed: bool) -> None:
    p = _line_params(po_id, it, removed=removed)
    p["id"] = line_id
    cur.execute(
        """
        UPDATE line_items SET
            product_raw = %(product_raw)s, product_name = %(product_name)s,
            container_size = %(container_size)s, quantity = %(quantity)s,
            unit_price = %(unit_price)s, line_total = %(line_total)s,
            additional_cost = %(additional_cost)s, sku = %(sku)s, is_sample = %(is_sample)s,
            revision_status = %(revision_status)s, is_removed = %(is_removed)s,
            voided = %(voided)s, void_reason = %(void_reason)s
        WHERE id = %(id)s AND po_id = %(po_id)s
        """,
        p,
    )


def save_po_edit(conn, po_id: int, header: dict, items: list[dict],
                 removed_items: list[dict] | None = None, *,
                 actor: str | None = None,
                 expected_version: int | None = None) -> dict:
    removed_items = removed_items or []
    data = {
        "subtotal": header.get("subtotal"),
        "tax": header.get("tax"),
        "total": header.get("total"),
        # voided lines are excluded from the qty×price=total reconciliation
        "line_items": [it for it in items if not it.get("voided")],
    }
    validate_math(data)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, po_number, customer_name, po_date, delivery_date, subtotal, tax, "
            "total, notes, status, edited_by, edited_at, lock_version "
            "FROM purchase_orders WHERE id = %s FOR UPDATE",
            (po_id,),
        )
        before = cur.fetchone()
        if before is None:
            raise NotFound("PO not found")
        if expected_version is not None and before["lock_version"] != expected_version:
            raise StaleWrite(
                current_version=before["lock_version"],
                edited_by=before["edited_by"],
                edited_at=before["edited_at"].isoformat() if before["edited_at"] else None,
            )
        if (before["status"] or "active") != "active":
            raise NotActive(before["status"])

        cur.execute(
            "SELECT id, is_removed FROM line_items WHERE po_id = %s", (po_id,)
        )
        existing = {r["id"]: r["is_removed"] for r in cur.fetchall()}

        cur.execute(
            """
            UPDATE purchase_orders SET
                po_number = %(po_number)s, customer_name = %(customer_name)s,
                po_date = %(po_date)s, delivery_date = %(delivery_date)s,
                subtotal = %(subtotal)s, tax = %(tax)s, total = %(total)s, notes = %(notes)s,
                math_check_failed = %(math_check_failed)s, math_check_detail = %(math_check_detail)s,
                edited = TRUE, edited_by = %(actor)s, edited_at = now(),
                lock_version = lock_version + 1
            WHERE id = %(po_id)s
            """,
            {
                "po_number": header.get("po_number"),
                "customer_name": header.get("customer_name"),
                "po_date": header.get("po_date") or None,
                "delivery_date": header.get("delivery_date") or None,
                "subtotal": header.get("subtotal"),
                "tax": header.get("tax"),
                "total": header.get("total"),
                "notes": header.get("notes"),
                "po_id": po_id,
                "actor": actor,
                "math_check_failed": data["math_check_failed"],
                "math_check_detail": data["math_check_detail"],
            },
        )

        # --- line diff by id: UPDATE kept, INSERT new, DELETE gone -------------
        keep_ids = {int(it["id"]) for it in (*items, *removed_items) if it.get("id")}
        gone = [lid for lid in existing if lid not in keep_ids]
        if gone:
            cur.execute("DELETE FROM line_items WHERE po_id = %s AND id = ANY(%s)", (po_id, gone))

        def _upsert(it: dict, *, removed: bool) -> None:
            lid = int(it["id"]) if it.get("id") and int(it["id"]) in existing else None
            if lid is not None:
                _update_line(cur, po_id, lid, it, removed=removed)
            else:
                _insert_line(cur, po_id, it, removed=removed)

        for it in items:
            _upsert(it, removed=False)
        for it in removed_items:
            _upsert(it, removed=True)

        new_version = before["lock_version"] + 1
        audit.log(
            conn, actor=actor, action="edit", entity="purchase_order", entity_id=po_id,
            before={
                "po_number": before["po_number"], "customer_name": before["customer_name"],
                "subtotal": _num(before["subtotal"]), "tax": _num(before["tax"]),
                "total": _num(before["total"]), "n_lines": len(existing),
            },
            after={
                "po_number": header.get("po_number"), "customer_name": header.get("customer_name"),
                "subtotal": header.get("subtotal"), "tax": header.get("tax"),
                "total": header.get("total"),
                "n_lines": len(items), "n_removed": len(removed_items),
                "lines_added": len(items) - sum(1 for it in items if it.get("id")),
                "lines_deleted": len(gone),
            },
        )
    conn.commit()
    return {
        "math_check_failed": bool(data["math_check_failed"]),
        "math_check_detail": data["math_check_detail"] or "",
        "lock_version": new_version,
    }


def _num(v):
    from decimal import Decimal

    return float(v) if isinstance(v, Decimal) else v
