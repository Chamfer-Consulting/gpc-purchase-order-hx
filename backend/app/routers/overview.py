"""GET /api/overview — placeholder. Phase 1 wires this to the real KPI + series
service (ported from dashboard/views/home.py + dashboard/data.py)."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..db import get_conn

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
def overview(user: AuthedUser = Depends(current_user)) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM purchase_orders WHERE error IS NULL OR error = ''")
        clean_pos = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM qbo_invoices")
        invoices = cur.fetchone()[0]

    return {
        "_stub": True,
        "generated_for": user.email or user.id,
        "kpis": [
            {"label": "Clean POs", "value": clean_pos},
            {"label": "Invoices synced", "value": invoices},
        ],
        "series": [],
    }
