"""GET /api/overview — PageResponse shape, same as the other analytics pages.
Scoped KPIs + monthly and year-over-year charts come from services/overview.py;
the "needs attention" digest is assembled here (it needs a live conn)."""

import time

import qbo_client  # shared/, via app.reuse
import qbo_matcher  # shared/, via app.reuse
from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..deps import FilterParams, filter_params
from ..reused_db import reused_conn
from ..schemas import AttentionItem, PageResponse
from ..services import review_queue
from ..services.overview import overview_page

router = APIRouter(prefix="/api", tags=["overview"])

_NOT_PO = "not a purchase order"
_SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2, "info": 3}
_HIDDEN_PRODUCTS = "SELECT product_name FROM hidden_products WHERE product_name IS NOT NULL"

# The digest is global (not filter-scoped) and its inputs change slowly, but it's
# ~10 queries + a big review-queue join on every landing. Cache it briefly.
_ATTN_TTL = 45.0
_attn_cache: tuple[float, list[AttentionItem]] | None = None


def _compute_attention(conn) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT li.po_id) FROM line_items li "
            "JOIN purchase_orders po ON po.id = li.po_id "
            "WHERE li.math_mismatch IS NOT NULL AND NOT li.is_removed "
            "  AND NOT COALESCE(li.voided, FALSE) AND NOT COALESCE(li.math_ack, FALSE) "
            "  AND po.status = 'active'"
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
            f"SELECT count(DISTINCT li.po_id) FROM line_items li "
            f"JOIN purchase_orders po ON po.id = li.po_id "
            f"WHERE li.price_anomaly IS NOT NULL AND NOT li.is_removed "
            f"  AND NOT COALESCE(li.voided, FALSE) AND po.status = 'active' "
            f"  AND li.product_name NOT IN ({_HIDDEN_PRODUCTS})"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="serious", count=n, href="/data-quality",
                                       title=f"{n} order(s) with a price anomaly"))

        cur.execute(
            "SELECT count(*) FROM purchase_orders "
            "WHERE status = 'active' AND error LIKE 'modification%%'"
        )
        if (n := cur.fetchone()[0]):
            items.append(AttentionItem(severity="serious", count=n, href="/reconcile",
                                       title=f"{n} unresolved order modification(s)"))

    q = review_queue.review_queue(conn)
    stale = sum(1 for x in q if x["stale"])
    if stale:
        items.append(AttentionItem(severity="serious", count=stale, href="/reconcile",
                                   title=f"{stale} extraction review(s) went stale"))
    if len(q) - stale:
        items.append(AttentionItem(severity="warning", count=len(q) - stale, href="/reconcile",
                                   title=f"{len(q) - stale} extraction(s) flagged for review"))

    if (unlinked := qbo_matcher.get_unlinked_pos(conn)):
        items.append(AttentionItem(severity="warning", count=len(unlinked), href="/reconcile",
                                   title=f"{len(unlinked)} PO(s) with no confirmed invoice match"))
    if (needs := qbo_matcher.get_needs_review(conn)):
        items.append(AttentionItem(severity="warning", count=len(needs), href="/reconcile",
                                   title=f"{len(needs)} match candidate(s) awaiting a decision"))

    qc = qbo_client.get_connection(conn)
    if qc and qc.get("auto_sync_error"):
        items.append(AttentionItem(severity="serious", href="/settings",
                                   title="QuickBooks auto-sync is failing"))

    items.sort(key=lambda it: (_SEV_ORDER[it.severity], -it.count))
    return items


def _attention(conn) -> list[AttentionItem]:
    """_compute_attention with a short process-wide TTL — the digest is global and
    slow-moving, so a burst of landings shares one computation."""
    global _attn_cache
    now = time.monotonic()
    if _attn_cache is not None and now - _attn_cache[0] < _ATTN_TTL:
        return _attn_cache[1]
    items = _compute_attention(conn)
    _attn_cache = (now, items)
    return items


@router.get("/overview", response_model=PageResponse)
def overview(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    # No response cache here: the digest is live and the analytics half must not
    # trail a PO edit / invoice link / QBO sync (the SPA already de-dupes with a
    # 5-min staleTime, and an explicit invalidate bypasses that on a mutation).
    resp = overview_page(fp)
    with reused_conn() as conn:
        resp.attention = _attention(conn)
    return resp
