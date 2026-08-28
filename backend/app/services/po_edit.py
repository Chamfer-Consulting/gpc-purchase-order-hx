"""Read + manual-edit one purchase order. Ported from dashboard/data.py:save_po_edit
(plain SQL + math_check.validate_math, no pandas) so the Edit PO page works now."""

import psycopg2.extras

from math_check import validate_math  # repo root, via app.reuse

_HEADER_COLS = (
    "id", "source_file", "po_number", "po_date", "delivery_date", "sent_date",
    "customer_name", "customer_id", "subtotal", "tax", "total", "notes",
    "math_check_failed", "math_check_detail", "edited", "edited_at", "gmail_thread_id",
)
_ITEM_COLS = (
    "id", "product_raw", "product_name", "container_size", "quantity", "unit_price",
    "line_total", "additional_cost", "sku", "is_sample", "math_mismatch",
    "price_anomaly", "revision_status", "is_removed",
)


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


def save_po_edit(conn, po_id: int, header: dict, items: list[dict],
                 removed_items: list[dict] | None = None) -> tuple[bool, str]:
    data = {
        "subtotal": header.get("subtotal"),
        "tax": header.get("tax"),
        "total": header.get("total"),
        "line_items": items,
    }
    validate_math(data)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE purchase_orders SET
                po_number = %(po_number)s, customer_name = %(customer_name)s,
                po_date = %(po_date)s, delivery_date = %(delivery_date)s,
                subtotal = %(subtotal)s, tax = %(tax)s, total = %(total)s, notes = %(notes)s,
                math_check_failed = %(math_check_failed)s, math_check_detail = %(math_check_detail)s,
                edited = TRUE, edited_at = now()
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
                "math_check_failed": data["math_check_failed"],
                "math_check_detail": data["math_check_detail"],
            },
        )
        cur.execute("DELETE FROM line_items WHERE po_id = %s", (po_id,))
        for it in items:
            _insert_line(cur, po_id, it, removed=False)
        for it in removed_items or []:
            _insert_line(cur, po_id, it, removed=True)
    conn.commit()
    return bool(data["math_check_failed"]), data["math_check_detail"] or ""


def _insert_line(cur, po_id: int, it: dict, *, removed: bool) -> None:
    cur.execute(
        """
        INSERT INTO line_items (
            po_id, product_raw, product_name, container_size,
            quantity, unit_price, line_total, additional_cost, sku, is_sample,
            math_mismatch, price_anomaly, revision_status, is_removed
        ) VALUES (
            %(po_id)s, %(product_raw)s, %(product_name)s, %(container_size)s,
            %(quantity)s, %(unit_price)s, %(line_total)s, %(additional_cost)s, %(sku)s, %(is_sample)s,
            %(math_mismatch)s, %(price_anomaly)s, %(revision_status)s, %(is_removed)s
        )
        """,
        {
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
            "math_mismatch": it.get("math_mismatch"),
            "price_anomaly": it.get("price_anomaly"),
            "revision_status": it.get("revision_status") or ("Removed" if removed else "Edited"),
            "is_removed": removed,
        },
    )
