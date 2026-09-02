"""Data Quality — the fix queue. Plain aggregations over purchase_orders /
line_items / qbo_invoices / po_invoice_links; no pandas. Ported from
dashboard/views/fulfillment_dataquality.py — same five categories, same
north-star (extraction success rate, genuine failures only).

Date/customer scoping (the FilterBar) applies to math checks, price anomalies,
questionable matches and invoice reconciliation. Extraction failures are NOT
scoped — an errored source usually has no usable date or customer.
"""

from decimal import Decimal

import psycopg2.extras
from fastapi import APIRouter, Depends

import qbo_matcher  # shared/, via app.reuse — customers_match()

from ..auth import AuthedUser, current_user
from ..deps import FilterParams, filter_params
from ..reused_db import reused_conn
from ..schemas import Kpi, PageResponse, Scope, Table, TableColumn

router = APIRouter(prefix="/api", tags=["quality"])

_NOT_PO = "not a purchase order"
_ROW_CAP = 300          # rows returned per table; the title notes "showing N of M"
_DATE_FAR_DAYS = 120    # confirmed match whose PO/invoice dates differ by more than this

# excludes hidden products, removed lines and voided lines — a stale flag on any
# of those isn't something a human can act on here.
_ACTIONABLE_LINE = (
    "NOT li.is_removed AND NOT COALESCE(li.voided, FALSE) "
    "AND li.product_name NOT IN "
    "  (SELECT product_name FROM hidden_products WHERE product_name IS NOT NULL)"
)
# math-check table also drops lines a human acknowledged as a genuine source-doc
# discrepancy (routers/po_admin.ack_line_math).
_NOT_MATH_ACKED = "AND NOT COALESCE(li.math_ack, FALSE)"


def _rows(cur) -> list[dict]:
    """cur must be a RealDictCursor — its rows are already dict-like."""
    return [dict(r) for r in cur.fetchall()]


def _jsonify(rows: list[dict]) -> list[dict]:
    """Coerce psycopg2 types the JSON encoder doesn't take — dates -> ISO strings,
    Decimal/numeric -> float — in place."""
    for r in rows:
        for k, v in r.items():
            if isinstance(v, Decimal):
                r[k] = float(v)
            elif hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return rows


def _scope(fp: FilterParams, date_col: str, customer_col: str) -> tuple[str, list]:
    """`(sql_fragment, params)` for date/customer scoping — each fragment is
    prefixed with AND, so append it inside an existing WHERE."""
    frags: list[str] = []
    params: list = []
    if fp.start:
        frags.append(f"{date_col} >= %s")
        params.append(fp.start)
    if fp.end:
        frags.append(f"{date_col} <= %s")
        params.append(fp.end)
    if fp.customers:
        frags.append(f"{customer_col} = ANY(%s)")
        params.append(list(fp.customers))
    return ((" AND " + " AND ".join(frags)) if frags else ""), params


def _title(base: str, shown: int, total: int) -> str:
    return f"{base} — showing {shown} of {total}" if total > shown else base


@router.get("/data-quality", response_model=PageResponse)
def data_quality(
    fp: FilterParams = Depends(filter_params),
    _: AuthedUser = Depends(current_user),
) -> PageResponse:
    with reused_conn() as conn:
        cur = conn.cursor()
        dcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # -- headline counts ------------------------------------------------
        cur.execute("SELECT count(*) FROM purchase_orders WHERE status = 'active'")
        total_active = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error IS NOT NULL AND error <> '' "
            "  AND error <> %s AND error NOT LIKE 'modification%%'",
            (_NOT_PO,),
        )
        real_errors = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM purchase_orders WHERE status = 'active' AND error = %s",
            (_NOT_PO,),
        )
        not_po = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error LIKE 'modification%%'"
        )
        unresolved_mods = cur.fetchone()[0]

        math_scope, math_p = _scope(fp, "po.po_date", "po.customer_name")
        cur.execute(
            f"SELECT count(DISTINCT li.po_id), count(*) FROM line_items li "
            f"JOIN purchase_orders po ON po.id = li.po_id "
            f"WHERE li.math_mismatch IS NOT NULL AND po.status = 'active' "
            f"  AND {_ACTIONABLE_LINE} {_NOT_MATH_ACKED}{math_scope}",
            math_p,
        )
        math_pos, math_total = cur.fetchone()

        price_scope, price_p = _scope(fp, "po.po_date", "po.customer_name")
        cur.execute(
            f"SELECT count(DISTINCT li.po_id), count(*) FROM line_items li "
            f"JOIN purchase_orders po ON po.id = li.po_id "
            f"WHERE li.price_anomaly IS NOT NULL AND po.status = 'active' "
            f"  AND {_ACTIONABLE_LINE}{price_scope}",
            price_p,
        )
        price_pos, price_total = cur.fetchone()

        # -- extraction failures (unscoped) -------------------------------
        dcur.execute(
            """
            SELECT po.id AS po_id, po.extracted_at, po.customer_name, po.source_file,
                   po.error, m.subject, m.from_addrs
            FROM purchase_orders po
            LEFT JOIN gmail_thread_meta m ON m.thread_id = po.gmail_thread_id
            WHERE po.status = 'active'
              AND po.error IS NOT NULL AND po.error <> ''
              AND po.error <> %s AND po.error NOT LIKE 'modification%%'
            ORDER BY po.extracted_at DESC NULLS LAST
            LIMIT %s
            """,
            (_NOT_PO, _ROW_CAP),
        )
        err_rows = _jsonify(_rows(dcur))

        # -- math-check failures ----------------------------------------
        dcur.execute(
            f"""
            SELECT po.id AS po_id, li.id AS line_id, po.po_number, po.customer_name, po.po_date,
                   li.product_name, li.container_size, li.quantity, li.unit_price,
                   li.line_total, li.math_mismatch
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.math_mismatch IS NOT NULL AND po.status = 'active'
              AND {_ACTIONABLE_LINE} {_NOT_MATH_ACKED}{math_scope}
            ORDER BY abs(coalesce(li.line_total, 0)) DESC, po.po_date DESC NULLS LAST
            LIMIT %s
            """,
            [*math_p, _ROW_CAP],
        )
        math_rows = _jsonify(_rows(dcur))

        # -- price anomalies (biggest dollar lines first) --------------
        dcur.execute(
            f"""
            SELECT po.id AS po_id, po.po_number, po.customer_name, po.po_date,
                   li.product_name, li.container_size, li.unit_price, li.line_total,
                   li.price_anomaly
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.price_anomaly IS NOT NULL AND po.status = 'active'
              AND {_ACTIONABLE_LINE}{price_scope}
            ORDER BY abs(coalesce(li.line_total, 0)) DESC, po.po_date DESC NULLS LAST
            LIMIT %s
            """,
            [*price_p, _ROW_CAP],
        )
        price_rows = _jsonify(_rows(dcur))

        # -- line items with no container size (biggest dollar lines first) ---
        # Their revenue lands in the "(no size)" reconciling row on Products &
        # Sizes. PO lines are fixable here (link jumps to the editor); invoice
        # lines are a QuickBooks-side mirror, listed for reference.
        ns_scope, ns_p = _scope(fp, "po.po_date", "po.customer_name")
        _NO_SIZE_PO = (
            "(li.container_size IS NULL OR btrim(li.container_size) = '') "
            "AND po.status = 'active' AND NOT COALESCE(li.is_sample, FALSE) "
            "AND li.product_name IS NOT NULL AND li.product_name NOT IN ('', 'UNKNOWN') "
            f"AND {_ACTIONABLE_LINE}"
        )
        dcur.execute(
            f"""
            SELECT po.id AS po_id, po.po_number, po.customer_name, po.po_date,
                   li.product_name, li.product_raw, li.quantity, li.unit_price, li.line_total
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE {_NO_SIZE_PO}{ns_scope}
            ORDER BY abs(coalesce(li.line_total, 0)) DESC, po.po_date DESC NULLS LAST
            LIMIT %s
            """,
            [*ns_p, _ROW_CAP],
        )
        nosize_po_rows = _jsonify(_rows(dcur))
        cur.execute(
            f"""
            SELECT count(DISTINCT li.po_id), count(*), COALESCE(SUM(abs(li.line_total)), 0)
            FROM line_items li JOIN purchase_orders po ON po.id = li.po_id
            WHERE {_NO_SIZE_PO}{ns_scope}
            """,
            ns_p,
        )
        nosize_po_pos, nosize_po_lines, nosize_po_money = cur.fetchone()
        nosize_po_money = float(nosize_po_money or 0)

        inv_ns_scope, inv_ns_p = _scope(fp, "inv.txn_date", "inv.customer_name")
        _NO_SIZE_INV = (
            "ii.category = 'product' "
            "AND (ii.container_size IS NULL OR btrim(ii.container_size) = '') "
            "AND NOT COALESCE(ii.is_sample, FALSE) "
            "AND ii.product_name IS NOT NULL AND ii.product_name NOT IN ('', 'UNKNOWN') "
            "AND (inv.private_note IS NULL OR inv.private_note NOT ILIKE '%%void%%') "
            "AND ii.product_name NOT IN "
            "  (SELECT product_name FROM hidden_products WHERE product_name IS NOT NULL)"
        )
        dcur.execute(
            f"""
            SELECT inv.doc_number, inv.customer_name, inv.txn_date,
                   ii.product_name, ii.quantity, ii.line_total
            FROM qbo_invoice_items ii JOIN qbo_invoices inv ON inv.id = ii.invoice_id
            WHERE {_NO_SIZE_INV}{inv_ns_scope}
            ORDER BY abs(coalesce(ii.line_total, 0)) DESC, inv.txn_date DESC NULLS LAST
            LIMIT %s
            """,
            [*inv_ns_p, _ROW_CAP],
        )
        nosize_inv_rows = _jsonify(_rows(dcur))
        cur.execute(
            f"""
            SELECT count(*), COALESCE(SUM(abs(ii.line_total)), 0)
            FROM qbo_invoice_items ii JOIN qbo_invoices inv ON inv.id = ii.invoice_id
            WHERE {_NO_SIZE_INV}{inv_ns_scope}
            """,
            inv_ns_p,
        )
        nosize_inv_lines, nosize_inv_money = cur.fetchone()
        nosize_inv_money = float(nosize_inv_money or 0)

        # -- questionable confirmed matches ---------------------------
        qm_scope, qm_p = _scope(fp, "inv.txn_date", "inv.customer_name")
        dcur.execute(
            f"""
            SELECT po.id AS po_id, po.po_number, po.customer_name AS po_customer,
                   COALESCE(po.po_date, po.sent_date::date) AS po_date, po.total AS po_total,
                   inv.doc_number, inv.customer_name AS invoice_customer,
                   inv.txn_date AS invoice_date, inv.total_amt AS invoice_total,
                   abs(COALESCE(po.po_date, po.sent_date::date) - inv.txn_date) AS day_gap
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE{qm_scope}
            """,
            qm_p,
        )
        qm_all = _rows(dcur)
        qm_flagged = []
        for r in qm_all:
            reasons = []
            if not qbo_matcher.customers_match(r["po_customer"], r["invoice_customer"]):
                reasons.append("customer")
            if r["day_gap"] is not None and r["day_gap"] > _DATE_FAR_DAYS:
                reasons.append("date gap")
            if reasons:
                r["reason"] = ", ".join(reasons)
                qm_flagged.append(r)
        qm_flagged.sort(key=lambda r: (r["day_gap"] is None, -(r["day_gap"] or 0)))
        qm_total = len(qm_flagged)
        qm_rows = _jsonify(qm_flagged[:_ROW_CAP])

        # -- invoice header total != sum of line items ---------------
        rec_scope, rec_p = _scope(fp, "i.txn_date", "i.customer_name")
        dcur.execute(
            f"""
            SELECT i.doc_number, i.customer_name, i.txn_date, i.total_amt,
                   COALESCE(s.li_sum, 0)  AS line_items_sum,
                   round(i.total_amt - COALESCE(s.li_sum, 0), 2) AS difference,
                   COALESCE(s.n_lines, 0) AS n_lines
            FROM qbo_invoices i
            LEFT JOIN (
                SELECT invoice_id, SUM(line_total) AS li_sum, COUNT(*) AS n_lines
                FROM qbo_invoice_items GROUP BY invoice_id
            ) s ON s.invoice_id = i.id
            WHERE i.total_amt IS NOT NULL AND i.total_amt <> 0
              AND (i.private_note IS NULL OR i.private_note NOT ILIKE '%%void%%')
              AND abs(i.total_amt - COALESCE(s.li_sum, 0)) > 0.02{rec_scope}
            ORDER BY abs(i.total_amt - COALESCE(s.li_sum, 0)) DESC
            LIMIT %s
            """,
            [*rec_p, _ROW_CAP],
        )
        rec_rows = _jsonify(_rows(dcur))
        cur.execute(
            f"""
            SELECT count(*) FROM qbo_invoices i
            LEFT JOIN (
                SELECT invoice_id, SUM(line_total) AS li_sum FROM qbo_invoice_items GROUP BY invoice_id
            ) s ON s.invoice_id = i.id
            WHERE i.total_amt IS NOT NULL AND i.total_amt <> 0
              AND (i.private_note IS NULL OR i.private_note NOT ILIKE '%%void%%')
              AND abs(i.total_amt - COALESCE(s.li_sum, 0)) > 0.02{rec_scope}
            """,
            rec_p,
        )
        rec_total = cur.fetchone()[0]

        # -- voided invoices (reference: they stay visible, never counted) ---
        cur.execute("SELECT count(*) FROM qbo_invoices WHERE private_note ILIKE '%void%'")
        void_all_time = cur.fetchone()[0]
        void_scope, void_p = _scope(fp, "i.txn_date", "i.customer_name")
        dcur.execute(
            f"""
            SELECT i.doc_number, i.customer_name, i.txn_date, i.total_amt, i.private_note AS note,
                   CASE WHEN EXISTS (SELECT 1 FROM po_invoice_links l
                                     WHERE l.invoice_id = i.id AND l.confirmed)
                        THEN 'yes' ELSE '—' END AS linked_to_a_po
            FROM qbo_invoices i
            WHERE i.private_note ILIKE '%%void%%'{void_scope}
            ORDER BY i.txn_date DESC NULLS LAST
            LIMIT %s
            """,
            [*void_p, _ROW_CAP],
        )
        void_rows = _jsonify(_rows(dcur))
        cur.execute(
            f"SELECT count(*) FROM qbo_invoices i WHERE i.private_note ILIKE '%%void%%'{void_scope}",
            void_p,
        )
        void_total = cur.fetchone()[0]

    success = round((total_active - real_errors) / total_active * 100, 1) if total_active else 100.0

    kpis = [
        Kpi(label="Extraction success", value=success, format="percent",
            help="Active PO rows that extracted without a genuine failure (all time)."),
        Kpi(label="Extraction failures", value=real_errors,
            delta=(f"+{not_po} classified 'not a PO'" if not_po else None)),
        Kpi(label="Math-check failures", value=math_pos),
        Kpi(label="Price anomalies", value=price_pos),
        Kpi(label="PO revenue · no size", value=nosize_po_money, format="currency",
            delta=(f"{nosize_po_lines} line(s) · {nosize_po_pos} PO(s)" if nosize_po_lines else None),
            help="Active PO line items with no container size — set it in the PO editor "
                 "(rows link through). Their revenue sits in the '(no size)' row on "
                 "Products & Sizes."),
        Kpi(label="Invoiced · no size", value=nosize_inv_money, format="currency",
            delta=(f"{nosize_inv_lines} line(s)" if nosize_inv_lines else None),
            help="QuickBooks invoice product lines with no size — reference only, fix in "
                 "QuickBooks. Approximate: excludes voided invoices and hidden products."),
        Kpi(label="Voided invoices", value=void_all_time,
            help="Invoices voided in QuickBooks (all time). They stay listed below "
                 "but never count toward revenue, matching or line-item totals."),
    ]

    tables = {
        "errors": Table(
            title=_title(f"Extraction failures ({real_errors})", len(err_rows), real_errors),
            columns=[
                TableColumn(key="po_id", label="PO id"),
                TableColumn(key="extracted_at", label="Failed at", kind="date"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="source_file", label="Source"),
                TableColumn(key="error", label="Error"),
                TableColumn(key="subject", label="Email subject"),
                TableColumn(key="from_addrs", label="From"),
            ],
            rows=err_rows,
            export_name="extraction_failures",
        ),
        "math": Table(
            title=_title(f"Math-check failures ({math_pos} PO(s), {math_total} line(s))",
                         len(math_rows), math_total),
            columns=[
                TableColumn(key="po_id", label="PO id"),
                TableColumn(key="po_number", label="PO #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="po_date", label="PO date", kind="date"),
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="container_size", label="Size"),
                TableColumn(key="quantity", label="Qty", kind="int"),
                TableColumn(key="unit_price", label="Unit price", kind="currency2"),
                TableColumn(key="line_total", label="Line total", kind="currency2"),
                TableColumn(key="math_mismatch", label="Detail"),
            ],
            rows=math_rows,
            export_name="math_failures",
        ),
        "price": Table(
            title=_title(f"Price anomalies ({price_pos} PO(s), {price_total} line(s))",
                         len(price_rows), price_total),
            columns=[
                TableColumn(key="po_id", label="PO id"),
                TableColumn(key="po_number", label="PO #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="po_date", label="PO date", kind="date"),
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="container_size", label="Size"),
                TableColumn(key="unit_price", label="Unit price", kind="currency2"),
                TableColumn(key="line_total", label="Line total", kind="currency2"),
                TableColumn(key="price_anomaly", label="Detail"),
            ],
            rows=price_rows,
            export_name="price_anomalies",
        ),
        "no_size_po": Table(
            title=_title(
                f"PO lines with no size ({nosize_po_pos} PO(s), {nosize_po_lines} line(s)) · "
                f"${nosize_po_money:,.0f}",
                len(nosize_po_rows), nosize_po_lines),
            columns=[
                TableColumn(key="po_id", label="PO id"),
                TableColumn(key="po_number", label="PO #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="po_date", label="PO date", kind="date"),
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="product_raw", label="Raw text"),
                TableColumn(key="quantity", label="Qty", kind="int"),
                TableColumn(key="unit_price", label="Unit price", kind="currency2"),
                TableColumn(key="line_total", label="Line total", kind="currency2"),
            ],
            rows=nosize_po_rows,
            export_name="no_size_po_lines",
        ),
        "no_size_invoice": Table(
            title=_title(
                f"Invoice lines with no size ({nosize_inv_lines}) · ${nosize_inv_money:,.0f}",
                len(nosize_inv_rows), nosize_inv_lines),
            columns=[
                TableColumn(key="doc_number", label="Invoice #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="txn_date", label="Date", kind="date"),
                TableColumn(key="product_name", label="Product"),
                TableColumn(key="quantity", label="Qty", kind="int"),
                TableColumn(key="line_total", label="Line total", kind="currency2"),
            ],
            rows=nosize_inv_rows,
            export_name="no_size_invoice_lines",
        ),
        "questionable_matches": Table(
            title=_title(f"Questionable confirmed matches ({qm_total})", len(qm_rows), qm_total),
            columns=[
                TableColumn(key="po_id", label="PO id"),
                TableColumn(key="po_number", label="PO #"),
                TableColumn(key="po_customer", label="PO customer"),
                TableColumn(key="po_date", label="PO date", kind="date"),
                TableColumn(key="doc_number", label="Invoice #"),
                TableColumn(key="invoice_customer", label="Invoice customer"),
                TableColumn(key="invoice_date", label="Invoice date", kind="date"),
                TableColumn(key="day_gap", label="Day gap", kind="int"),
                TableColumn(key="reason", label="Why flagged"),
            ],
            rows=qm_rows,
            export_name="questionable_matches",
        ),
        "invoice_recon": Table(
            title=_title(f"Invoice total ≠ sum of line items ({rec_total})", len(rec_rows), rec_total),
            columns=[
                TableColumn(key="doc_number", label="Invoice #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="txn_date", label="Date", kind="date"),
                TableColumn(key="total_amt", label="Header total", kind="currency2"),
                TableColumn(key="line_items_sum", label="Σ line items", kind="currency2"),
                TableColumn(key="difference", label="Difference", kind="currency2"),
                TableColumn(key="n_lines", label="Lines", kind="int"),
            ],
            rows=rec_rows,
            export_name="invoice_reconciliation",
        ),
        "voided": Table(
            title=_title(f"Voided invoices ({void_total})", len(void_rows), void_total),
            columns=[
                TableColumn(key="doc_number", label="Invoice #"),
                TableColumn(key="customer_name", label="Customer"),
                TableColumn(key="txn_date", label="Date", kind="date"),
                TableColumn(key="total_amt", label="Total", kind="currency2"),
                TableColumn(key="linked_to_a_po", label="Linked to a PO"),
                TableColumn(key="note", label="QBO note"),
            ],
            rows=void_rows,
            export_name="voided_invoices",
        ),
    }

    notes = []
    if unresolved_mods:
        notes.append(
            f"{unresolved_mods} unresolved order modification(s) — link each to the PO "
            "it revises on Reconcile; a re-run can't resolve the target."
        )
    notes.append(
        "Invoice ≠ line items is QuickBooks-side and reference-only — it stops the "
        "line-item revenue views reconciling to gross invoiced."
    )
    if nosize_po_lines or nosize_inv_lines:
        notes.append(
            "“No size” lines carry revenue but no container size, so it lands in the "
            "“(no size)” row on Products & Sizes. Fix PO lines in the editor; invoice "
            "lines are a QuickBooks mirror and are fixed there."
        )

    return PageResponse(
        scope=Scope(count=real_errors + math_pos + price_pos + qm_total + nosize_po_lines,
                    noun="issues"),
        kpis=kpis,
        tables=tables,
        notes=notes,
    )
