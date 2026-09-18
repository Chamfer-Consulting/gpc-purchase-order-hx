"""GET /api/filters/options — the distinct values that populate the SPA's
customer / product / size MultiSelects."""

from fastapi import APIRouter, Depends

from ..auth import PO_ANALYTICS_PAGES, AuthedUser, require_page
from ..cache import cached
from ..reused_db import reused_conn

router = APIRouter(prefix="/api/filters", tags=["filters"])


@router.get("/options")
# FastAPI calls the endpoint with keyword args only (`_=<AuthedUser>`), so the
# key_fn must accept **kwargs — a fixed `lambda user:` raised TypeError on every
# call and turned this endpoint into a 500 (empty MultiSelects on every page).
@cached(lambda *_a, **_k: "options")
# Shared PO/QBO metadata (customer/product/size names) reused by every
# PO-analytics page's FilterBar, not tied to one specific nav page — an
# external_viewer with any *one* of those pages granted needs it. Pricing
# and Yields are deliberately excluded (PO_ANALYTICS_PAGES, not the full
# EXTERNAL_VIEWABLE_PAGES) — neither ever calls this endpoint, and a
# Yields- or Pricing-only grant has no legitimate reason to pull the full
# cross-customer PO/QBO name lists this returns.
def options(_: AuthedUser = Depends(require_page(*PO_ANALYTICS_PAGES))) -> dict:
    with reused_conn() as conn, conn.cursor() as cur:
        # exclude the Settings → Visibility hidden sets — a filter can't usefully
        # scope to an account / product whose data is dropped from every page.
        cur.execute(
            "SELECT DISTINCT customer_name FROM qbo_invoices "
            "WHERE customer_name IS NOT NULL "
            "AND customer_name NOT IN (SELECT customer_name FROM hidden_customers) "
            "ORDER BY customer_name"
        )
        customers = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT product_name FROM qbo_invoice_items "
            "WHERE product_name IS NOT NULL AND category = 'product' "
            "AND product_name <> 'UNKNOWN' "
            "AND product_name NOT IN (SELECT product_name FROM hidden_products) "
            "ORDER BY product_name"
        )
        products = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT container_size FROM qbo_invoice_items "
            "WHERE container_size IS NOT NULL AND container_size <> '' "
            "AND category = 'product' ORDER BY container_size"
        )
        sizes = [r[0] for r in cur.fetchall()]
    return {"customers": customers, "products": products, "sizes": sizes}
