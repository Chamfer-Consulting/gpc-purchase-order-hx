"""Read-only analytics pages. Each returns a PageResponse and takes the shared
FilterParams.

customers / products are wired to real services (dashboard/data.py, called
headless). explore / lifecycle are still stubs pending their ports
(docs/REBUILD-TODO.md §2.3)."""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..cache import cached
from ..deps import FilterParams, filter_params
from ..schemas import PageResponse, Scope
from ..services.customers import customer_360
from ..services.products import products_and_sizes

router = APIRouter(prefix="/api", tags=["analytics"])


def _key(*args, **kwargs):
    """Cache key for a page endpoint — everything but the FilterParams is the same
    for all authed users. FastAPI passes deps by keyword."""
    fp = kwargs.get("fp") or (args[0] if args else None)
    return fp.cache_key() if fp is not None else ()


def _stub(noun: str, fp: FilterParams) -> PageResponse:
    return PageResponse(
        stub=True,
        scope=Scope(
            count=0,
            noun=noun,
            start=fp.start,
            end=fp.end,
            note="Not ported yet — see docs/REBUILD-TODO.md §2.3.",
        ),
    )


@router.get("/customers", response_model=PageResponse)
@cached(_key)
def customers(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return customer_360(fp)


@router.get("/products", response_model=PageResponse)
@cached(_key)
def products(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return products_and_sizes(fp)


@router.get("/explore", response_model=PageResponse)
def explore(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return _stub("POs", fp)


@router.get("/lifecycle", response_model=PageResponse)
def lifecycle(fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)) -> PageResponse:
    return _stub("orders", fp)
