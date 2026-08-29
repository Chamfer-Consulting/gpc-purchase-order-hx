"""GET /api/filters/options — the distinct values that populate the SPA's
customer / product / size MultiSelects."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..cache import cached
from ..reused_db import reused_conn

router = APIRouter(prefix="/api/filters", tags=["filters"])


@router.get("/options")
@cached(lambda user: "options")
def options(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT customer_name FROM qbo_invoices "
            "WHERE customer_name IS NOT NULL ORDER BY customer_name"
        )
        customers = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT product_name FROM qbo_invoice_items "
            "WHERE product_name IS NOT NULL AND category = 'product' "
            "AND product_name <> 'UNKNOWN' ORDER BY product_name"
        )
        products = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT container_size FROM qbo_invoice_items "
            "WHERE container_size IS NOT NULL AND container_size <> '' ORDER BY container_size"
        )
        sizes = [r[0] for r in cur.fetchall()]
    return {"customers": customers, "products": products, "sizes": sizes}
