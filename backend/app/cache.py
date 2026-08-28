"""Tiny in-process TTL cache for expensive read endpoints — the counterpart to
Streamlit's st.cache_data(ttl=). Single-instance only; if the API ever runs on
more than one machine, move this to Supabase materialized views or Redis
(see docs/REBUILD-TODO.md Phase 5)."""

from collections.abc import Callable, Hashable
from functools import wraps
from typing import TypeVar

from cachetools import TTLCache

_T = TypeVar("_T")

# ~5 min, generous size — the payloads are small JSON dicts.
_store: TTLCache = TTLCache(maxsize=512, ttl=300)


def cached(key_fn: Callable[..., Hashable]):
    """Decorator: memoise a sync function's return for the TTL, keyed by key_fn(*args)."""

    def deco(fn: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> _T:
            k = (fn.__qualname__, key_fn(*args, **kwargs))
            if k in _store:
                return _store[k]
            val = fn(*args, **kwargs)
            _store[k] = val
            return val

        return wrapper

    return deco


def clear() -> None:
    _store.clear()
