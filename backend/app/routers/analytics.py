"""Read-only analytics pages. Each endpoint returns a PageResponse and takes the
shared FilterParams. Bodies are stubs until the service layer lands
(docs/REBUILD-TODO.md §0.4 / §2.3) — they return the correct shape with empty
data so the SPA is fully buildable now.

When a service module exists, replace the stub body with e.g.:
    from ..services.customers import customer_360
    return customer_360(fp)
and wrap the read in app.cache.cached(lambda fp, user: fp.cache_key()).
"""

from fastapi import APIRouter, Depends

from ..auth import AuthedUser, current_user
from ..deps import FilterParams, filter_params
from ..schemas import PageResponse, Scope

router = APIRouter(prefix="/api", tags=["analytics"])


def _stub(noun: str, fp: FilterParams) -> PageResponse:
    return PageResponse(
        stub=True,
        scope=Scope(
            count=0,
            noun=noun,
            start=fp.start,
            end=fp.end,
            note="Service layer not wired yet — see docs/REBUILD-TODO.md §2.3.",
        ),
    )


@router.get("/customers", response_model=PageResponse)
def customers(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    return _stub("customers", fp)


@router.get("/products", response_model=PageResponse)
def products(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    return _stub("POs", fp)


@router.get("/explore", response_model=PageResponse)
def explore(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    return _stub("POs", fp)


@router.get("/lifecycle", response_model=PageResponse)
def lifecycle(
    fp: FilterParams = Depends(filter_params), _: AuthedUser = Depends(current_user)
) -> PageResponse:
    return _stub("orders", fp)
