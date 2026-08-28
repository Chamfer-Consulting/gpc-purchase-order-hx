"""GET /api/overview — PageResponse shape, same as the other analytics pages.
KPIs + the "needs attention" digest are real (direct SQL + the reused matcher);
charts land when home.py's series logic moves into services/overview.py."""

import qbo_client  # dashboard/, via app.reuse
import qbo_matcher  # dashboard/, via app.reuse
from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..deps import FilterParams, filter_params
from ..reused_db import reused_conn
from ..schemas import AttentionItem, Kpi, PageResponse, Scope
from ..services import review_queue

router = APIRouter(prefix="/api", tags=["overview"])

_NOT_PO = "not a purchase order"
_SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2, "info": 3}


def _attention(conn) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT po_id) FROM line_items "
            "WHERE math_mismatch IS NOT NULL AND NOT is_removed"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="critical", count=n, href="/data-quality",
                                       title=f"{n} order(s) fail the math check"))

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE error IS NOT NULL AND error <> '' AND error <> %s AND error NOT LIKE 'modification%%'",
            (_NOT_PO,),
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="critical", count=n, href="/data-quality",
                                       title=f"{n} source(s) failed extraction"))

        cur.execute(
            "SELECT count(DISTINCT po_id) FROM line_items "
            "WHERE price_anomaly IS NOT NULL AND NOT is_removed"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="serious", count=n, href="/data-quality",
                                       title=f"{n} order(s) with a price anomaly"))

        cur.execute("SELECT count(*) FROM purchase_orders WHERE error LIKE 'modification%%'")
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="serious", count=n, href="/review",
                                       title=f"{n} unresolved order modification(s)"))

    q = review_queue.review_queue(conn)
    stale = sum(1 for x in q if x["stale"])
    if stale:
        items.append(AttentionItem(severity="serious", count=stale, href="/review",
                                   title=f"{stale} extraction review(s) went stale"))
    if len(q) - stale:
        items.append(AttentionItem(severity="warning", count=len(q) - stale, href="/review",
                                   title=f"{len(q) - stale} extraction(s) flagged for review"))

    if (unlinked := qbo_matcher.get_unlinked_pos(conn)):
        items.append(AttentionItem(severity="warning", count=len(unlinked), href="/match",
                                   title=f"{len(unlinked)} PO(s) with no confirmed invoice match"))
    if (needs := qbo_matcher.get_needs_review(conn)):
        items.append(AttentionItem(severity="warning", count=len(needs), href="/match",
                                   title=f"{len(needs)} match candidate(s) awaiting a decision"))

    qc = qbo_client.get_connection(conn)
    if qc and qc.get("auto_sync_error"):
        items.append(AttentionItem(severity="serious", href="/settings",
                                   title="QuickBooks auto-sync is failing"))

    items.sort(key=lambda it: (_SEV_ORDER[it.severity], -it.count))
    return items


@router.get("/overview", response_model=PageResponse)
def overview(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    with reused_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM purchase_orders WHERE error IS NULL OR error = ''")
            clean_pos = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM qbo_invoices")
            invoices = cur.fetchone()[0]
            cur.execute(
                "SELECT coalesce(sum(line_total), 0) FROM qbo_invoice_items WHERE category = 'product'"
            )
            revenue = float(cur.fetchone()[0] or 0)
        attention = _attention(conn)

    return PageResponse(
        stub=True,
        scope=Scope(
            count=clean_pos, noun="POs", start=fp.start, end=fp.end,
            note="Charts + date-scoped KPIs land with services/overview.py.",
        ),
        attention=attention,
        kpis=[
            Kpi(label="Product revenue (all time)", value=revenue, format="currency"),
            Kpi(label="Clean POs", value=clean_pos, format="int"),
            Kpi(label="Invoices synced", value=invoices, format="int"),
        ],
    )
