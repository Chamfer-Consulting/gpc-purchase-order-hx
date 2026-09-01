"""Data Quality — the fix queue. Plain aggregations over purchase_orders /
line_items / qbo_invoices; no pandas, so it's real here rather than a stub.
Mirrors dashboard/views/fulfillment_dataquality.py's categories."""

import psycopg2.extras
from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..reused_db import reused_conn
from ..schemas import PageResponse, Scope, Table, TableColumn

router = APIRouter(prefix="/api", tags=["quality"])

_NOT_PO = "not a purchase order"


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/data-quality", response_model=PageResponse)
def data_quality(_: AuthedUser = Depends(current_user)) -> PageResponse:
    with reused_conn() as conn, conn.cursor() as cur:
        # Every count is scoped to status = 'active' — cancelled / voided / deleted
        # POs are out of the fix queue.
        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error IS NOT NULL AND error <> '' AND error <> %s "
            "AND error NOT LIKE 'modification%%'",
            (_NOT_PO,),
        )
        real_errors = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM purchase_orders WHERE status = 'active' AND error = %s",
            (_NOT_PO,),
        )
        not_po = cur.fetchone()[0]

        cur.execute(
            "SELECT count(DISTINCT li.po_id) FROM line_items li "
            "JOIN purchase_orders po ON po.id = li.po_id "
            "WHERE li.math_mismatch IS NOT NULL AND NOT li.is_removed AND po.status = 'active'"
        )
        math_pos = cur.fetchone()[0]

        cur.execute(
            "SELECT count(DISTINCT li.po_id) FROM line_items li "
            "JOIN purchase_orders po ON po.id = li.po_id "
            "WHERE li.price_anomaly IS NOT NULL AND NOT li.is_removed AND po.status = 'active'"
        )
        price_pos = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error LIKE 'modification%%'"
        )
        unresolved_mods = cur.fetchone()[0]

        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute(
            """
            SELECT po.id AS po_id, po.source_file, po.error, po.customer_name,
                   po.po_date, m.subject, m.from_addrs, m.url AS gmail_url
            FROM purchase_orders po
            LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
            WHERE po.status = 'active'
              AND po.error IS NOT NULL AND po.error <> '' AND po.error <> %s
            ORDER BY po.extracted_at DESC LIMIT 200
            """,
            (_NOT_PO,),
        )
        errors = [
            {**r, "po_date": r["po_date"].isoformat() if r["po_date"] else None}
            for r in cur2.fetchall()
        ]

        cur2.execute(
            """
            SELECT po.id AS po_id, po.po_number, po.customer_name, po.po_date,
                   li.product_name, li.container_size, li.math_mismatch
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.math_mismatch IS NOT NULL AND NOT li.is_removed AND po.status = 'active'
            ORDER BY po.po_date DESC NULLS LAST LIMIT 200
            """
        )
        math_rows = [
            {**r, "po_date": r["po_date"].isoformat() if r["po_date"] else None}
            for r in cur2.fetchall()
        ]

        cur2.execute(
            """
            SELECT po.id AS po_id, po.po_number, po.customer_name,
                   li.product_name, li.container_size, li.unit_price, li.price_anomaly
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.price_anomaly IS NOT NULL AND NOT li.is_removed AND po.status = 'active'
            ORDER BY po.po_date DESC NULLS LAST LIMIT 200
            """
        )
        price_rows = _rows(cur2)

    return PageResponse(
        scope=Scope(count=real_errors + math_pos + price_pos + unresolved_mods, noun="issues"),
        kpis=[],
        tables={
            "errors": Table(
                title=f"Extraction failures ({real_errors}) — genuine errors only, not “not a purchase order” ({not_po})",
                columns=[
                    # identifier, not a quantity — must not be thousands-grouped ("23,692")
                    TableColumn(key="po_id", label="PO id"),
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="po_date", label="PO date", kind="date"),
                    TableColumn(key="error", label="Error"),
                    TableColumn(key="subject", label="Email subject"),
                    TableColumn(key="from_addrs", label="From"),
                ],
                rows=errors,
                export_name="extraction_failures",
            ),
            "math": Table(
                title=f"Math-check failures ({math_pos} PO(s))",
                columns=[
                    TableColumn(key="po_number", label="PO"),
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="po_date", label="PO date", kind="date"),
                    TableColumn(key="product_name", label="Product"),
                    TableColumn(key="container_size", label="Size"),
                    TableColumn(key="math_mismatch", label="Detail"),
                ],
                rows=math_rows,
                export_name="math_failures",
            ),
            "price": Table(
                title=f"Price anomalies ({price_pos} PO(s))",
                columns=[
                    TableColumn(key="po_number", label="PO"),
                    TableColumn(key="customer_name", label="Customer"),
                    TableColumn(key="product_name", label="Product"),
                    TableColumn(key="container_size", label="Size"),
                    TableColumn(key="unit_price", label="Unit price", kind="currency2"),
                    TableColumn(key="price_anomaly", label="Detail"),
                ],
                rows=price_rows,
                export_name="price_anomalies",
            ),
        },
        notes=(
            [f"{unresolved_mods} unresolved modification(s) — link them on Extraction Review."]
            if unresolved_mods
            else []
        ),
    )
