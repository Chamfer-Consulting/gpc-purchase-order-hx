"""Shared request dependencies. `FilterParams` mirrors the SPA's URL scope
(web/src/filters/useFilters.ts) — every analytics endpoint takes it."""

from dataclasses import dataclass

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


def _clean(v: list[str] | None) -> tuple[str, ...]:
    return tuple(p.strip() for p in (v or []) if p and p.strip())


def filter_params(
    start: str | None = Query(None),
    end: str | None = Query(None),
    # repeated keys (?customers=a&customers=b) so a value with a comma survives —
    # see web/src/filters/useFilters.ts. A stray legacy "a,b" is taken literally.
    customers: list[str] | None = Query(None),
    products: list[str] | None = Query(None),
    sizes: list[str] | None = Query(None),
    include_samples: str | None = Query(None),
) -> FilterParams:
    return FilterParams(
        start=start,
        end=end,
        customers=_clean(customers),
        products=_clean(products),
        sizes=_clean(sizes),
        include_samples=include_samples in ("1", "true", "True"),
    )
