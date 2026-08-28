"""GET /api/overview — the same PageResponse shape as the other analytics pages,
so the SPA renders it through the shared PageRenderer. Body is a stub (real KPI
numbers are already available from a couple of counts) until home.py's logic moves
into services/overview.py."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..db import get_conn
from ..deps import FilterParams, filter_params
from ..schemas import Kpi, PageResponse, Scope

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview", response_model=PageResponse)
def overview(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM purchase_orders WHERE error IS NULL OR error = ''")
        clean_pos = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM qbo_invoices")
        invoices = cur.fetchone()[0]
        cur.execute("SELECT coalesce(sum(line_total), 0) FROM qbo_invoice_items WHERE category = 'product'")
        revenue = float(cur.fetchone()[0] or 0)

    return PageResponse(
        stub=True,
        scope=Scope(count=clean_pos, noun="POs", start=fp.start, end=fp.end,
                    note="Real KPIs, charts and the attention digest land with services/overview.py."),
        kpis=[
            Kpi(label="Revenue", value=revenue, format="currency"),
            Kpi(label="Clean POs", value=clean_pos, format="int"),
            Kpi(label="Invoices synced", value=invoices, format="int"),
        ],
    )
