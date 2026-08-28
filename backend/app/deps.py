"""Shared request dependencies. `FilterParams` mirrors the SPA's URL scope
(web/src/filters/useFilters.ts) — every analytics endpoint takes it."""

from dataclasses import dataclass, field

from fastapi import Query


@dataclass(frozen=True)
class FilterParams:
    start: str | None = None
    end: str | None = None
    customers: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    sizes: tuple[str, ...] = ()
    include_samples: bool = False

    def cache_key(self) -> tuple:
        return (self.start, self.end, self.customers, self.products, self.sizes, self.include_samples)


def _split(v: str | None) -> tuple[str, ...]:
    return tuple(p for p in (v or "").split(",") if p.strip())


def filter_params(
    start: str | None = Query(None),
    end: str | None = Query(None),
    customers: str | None = Query(None, description="comma-separated"),
    products: str | None = Query(None, description="comma-separated"),
    sizes: str | None = Query(None, description="comma-separated"),
    include_samples: str | None = Query(None),
) -> FilterParams:
    return FilterParams(
        start=start,
        end=end,
        customers=_split(customers),
        products=_split(products),
        sizes=_split(sizes),
        include_samples=include_samples in ("1", "true", "True"),
    )
