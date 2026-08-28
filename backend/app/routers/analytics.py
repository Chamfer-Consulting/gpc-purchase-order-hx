"""Read-only analytics pages. Each returns a PageResponse and takes the shared
FilterParams. All four are wired to services that call dashboard/data.py headless."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..cache import cached
from ..deps import FilterParams, filter_params
from ..schemas import PageResponse
from ..services.customers import customer_360
from ..services.explore import explore as explore_svc
from ..services.lifecycle import order_lifecycle
from ..services.products import products_and_sizes

router = APIRouter(prefix="/api", tags=["analytics"])


def _key(*args, **kwargs):
    """Cache key — everything but the FilterParams is the same for all authed
    users. FastAPI passes deps by keyword."""
    fp = kwargs.get("fp") or (args[0] if args else None)
    return fp.cache_key() if fp is not None else ()


@router.get("/customers", response_model=PageResponse)
@cached(_key)
def customers(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return customer_360(fp)


@router.get("/products", response_model=PageResponse)
@cached(_key)
def products(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return products_and_sizes(fp)


@router.get("/explore", response_model=PageResponse)
@cached(_key)
def explore(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return explore_svc(fp)


@router.get("/lifecycle", response_model=PageResponse)
@cached(_key)
def lifecycle(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return order_lifecycle(fp)
