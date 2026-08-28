"""psycopg2 connections for the reused repo modules (gmail_client, qbo_client,
qbo_matcher, sync_dashboard, ...). Those are written against psycopg2 — Json /
execute_values / etc. — so they can't take the app's psycopg3 pool connections.
Short-lived, opened per operation, against the same DATABASE_URL.

New service-layer code uses app.db.get_conn() (psycopg3 pool) instead."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2

from .config import get_settings


@contextmanager
def reused_conn() -> Iterator["psycopg2.extensions.connection"]:
    conn = psycopg2.connect(get_settings().database_url)
    try:
        yield conn
    finally:
        conn.close()
