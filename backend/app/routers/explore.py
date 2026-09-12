"""Explore's pivot configurator and two-period comparison. The base
GET /api/explore (default PageResponse) stays in routers/analytics.py."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import AuthedUser, current_user
from ..cache import cached
from ..deps import FilterParams, filter_params
from ..schemas import PageResponse
from ..services.explore import compare as compare_svc
from ..services.explore import pivot as pivot_svc

router = APIRouter(prefix="/api/explore", tags=["explore"])


def _key(*args, **kwargs):
    fp = kwargs.get("fp")
    extra = tuple(sorted((k, str(v)) for k, v in kwargs.items() if k != "fp" and k != "_"))
    return ((fp.cache_key() if fp is not None else ()), extra)


@router.get("/pivot", response_model=PageResponse)
@cached(_key)
def pivot(
    measure: str = Query("revenue"),
    grain: str = Query("month"),
    dims: str = Query("customer", description="comma list: customer, product, size"),
    fp: FilterParams = Depends(filter_params),
    _: AuthedUser = Depends(current_user),
) -> PageResponse:
    dim_list = [d.strip() for d in dims.split(",") if d.strip()]
    return pivot_svc(fp, measure, grain, dim_list)


@router.get("/compare", response_model=PageResponse)
@cached(_key)
def compare(
    a_start: str = Query(...),
    a_end: str = Query(...),
    b_start: str = Query(...),
    b_end: str = Query(...),
    fp: FilterParams = Depends(filter_params),
    _: AuthedUser = Depends(current_user),
) -> PageResponse:
    for v in (a_start, a_end, b_start, b_end):
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise HTTPException(422, "dates must be YYYY-MM-DD")
    return compare_svc(fp, a_start, a_end, b_start, b_end)
