"""Reference Prices — the price table behind the price-anomaly flag, plus the
unit-price history that informs an edit. Reads are open to any signed-in user;
writing a reference price is admin-only (it changes what every future extraction
flags as anomalous). See services/pricing.py."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_admin
from ..reused_db import reused_conn
from ..services import pricing

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id


class RefPriceRow(BaseModel):
    customer_name: str
    product_name: str
    container_size: str
    price: float


class SaveIn(BaseModel):
    rows: list[RefPriceRow] = []
    delete: list[list[str]] = []  # [[customer, product, size], ...]


@router.get("")
def list_prices(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return {
            "reference_prices": pricing.list_reference_prices(conn),
            "options": pricing.price_options(conn),
        }


@router.get("/history")
def history(product: str, size: str, _: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return pricing.price_history(conn, product, size)


@router.post("")
def save_prices(body: SaveIn, user: AuthedUser = Depends(require_admin)) -> dict:
    actor = _actor(user)
    with reused_conn() as conn:
        # one transaction: a failed delete must not leave the save committed
        saved = pricing.save_reference_prices(
            conn, [r.model_dump() for r in body.rows], actor, commit=False
        )
        deleted = pricing.delete_reference_prices(conn, body.delete, actor, commit=False)
        conn.commit()
    return {"ok": True, "saved": saved, "deleted": deleted}
