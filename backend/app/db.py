"""One psycopg3 connection pool for the whole process, against the Supabase
transaction pooler. Short-lived checkouts only — no long transactions here (those
belong to the pipeline scripts on the session connection)."""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    s = get_settings()
    _pool = ConnectionPool(
        conninfo=s.database_url,
        min_size=s.db_pool_min,
        max_size=s.db_pool_max,
        kwargs={"connect_timeout": 15},
        open=True,
        name="po-dashboard-api",
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator["psycopg.Connection"]:  # noqa: F821
    if _pool is None:
        init_pool()
    assert _pool is not None
    with _pool.connection() as conn:
        yield conn
