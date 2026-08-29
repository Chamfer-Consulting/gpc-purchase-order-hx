"""GET /api/overview — PageResponse shape, same as the other analytics pages.
Scoped KPIs + monthly and year-over-year charts come from services/overview.py;
the "needs attention" digest is assembled here (it needs a live conn)."""

import qbo_client  # dashboard/, via app.reuse
import qbo_matcher  # dashboard/, via app.reuse
from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..cache import cached
from ..deps import FilterParams, filter_params
from ..reused_db import reused_conn
from ..schemas import AttentionItem, PageResponse
from ..services import review_queue
from ..services.overview import overview_page

router = APIRouter(prefix="/api", tags=["overview"])

_NOT_PO = "not a purchase order"
_SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2, "info": 3}


def _attention(conn) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT li.po_id) FROM line_items li "
            "JOIN purchase_orders po ON po.id = li.po_id "
            "WHERE li.math_mismatch IS NOT NULL AND NOT li.is_removed AND po.status = 'active'"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="critical", count=n, href="/data-quality",
                                       title=f"{n} order(s) fail the math check"))

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error IS NOT NULL AND error <> '' AND error <> %s "
            "AND error NOT LIKE 'modification%%'",
            (_NOT_PO,),
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="critical", count=n, href="/data-quality",
                                       title=f"{n} source(s) failed extraction"))

        cur.execute(
            "SELECT count(DISTINCT li.po_id) FROM line_items li "
            "JOIN purchase_orders po ON po.id = li.po_id "
            "WHERE li.price_anomaly IS NOT NULL AND NOT li.is_removed AND po.status = 'active'"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="serious", count=n, href="/data-quality",
                                       title=f"{n} order(s) with a price anomaly"))

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error LIKE 'modification%%'"
        )
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


@cached(lambda fp: fp.cache_key())
def _cached_page(fp: FilterParams) -> PageResponse:
    """The analytics half — pure fp → PageResponse, safe to memoise. The attention
    digest is recomputed per request (live counts) and attached by the route."""
    return overview_page(fp)


@router.get("/overview", response_model=PageResponse)
def overview(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    resp = _cached_page(fp).model_copy()
    with reused_conn() as conn:
        resp.attention = _attention(conn)
    return resp
