"""Settings — product visibility (hidden_products) and saved views
(dashboard_saved_views). Direct SQL on a reused psycopg2 conn; ported from
dashboard/data.py's set_product_hidden / load_saved_views / save_view /
delete_view and dashboard/views/settings.py."""

from __future__ import annotations

import json

import psycopg2
import psycopg2.extras

_VIEWS_DDL = """
CREATE TABLE IF NOT EXISTS dashboard_saved_views (
    name TEXT PRIMARY KEY, kind TEXT NOT NULL, config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def list_products(conn) -> list[dict]:
    """Every product name seen on an active PO (plus any still-hidden name that no
    longer appears), each with its current hidden flag and a usage count."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH seen AS (
                SELECT li.product_name, count(*) AS n_lines
                FROM line_items li
                JOIN purchase_orders po ON po.id = li.po_id
                WHERE po.status = 'active'
                  AND li.product_name IS NOT NULL AND li.product_name <> ''
                GROUP BY li.product_name
            )
            SELECT COALESCE(s.product_name, h.product_name) AS product_name,
                   COALESCE(s.n_lines, 0) AS n_lines,
                   (h.product_name IS NOT NULL) AS hidden
            FROM seen s
            FULL OUTER JOIN hidden_products h ON h.product_name = s.product_name
            ORDER BY 1
            """
        )
        return [dict(r) for r in cur.fetchall()]


def set_product_hidden(conn, product_name: str, hidden: bool) -> None:
    with conn.cursor() as cur:
        if hidden:
            cur.execute(
                "INSERT INTO hidden_products (product_name) VALUES (%s) "
                "ON CONFLICT (product_name) DO NOTHING",
                (product_name,),
            )
        else:
            cur.execute("DELETE FROM hidden_products WHERE product_name = %s", (product_name,))
    conn.commit()


def list_views(conn, kind: str) -> list[dict]:
    with conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name, config FROM dashboard_saved_views WHERE kind = %s ORDER BY created_at",
                (kind,),
            )
            return [{"name": n, "config": c} for n, c in cur.fetchall()]
        except psycopg2.Error:
            conn.rollback()
            return []


def save_view(conn, kind: str, name: str, config: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(_VIEWS_DDL)
        cur.execute(
            "INSERT INTO dashboard_saved_views (name, kind, config) VALUES (%s, %s, %s) "
            "ON CONFLICT (name) DO UPDATE SET kind = EXCLUDED.kind, config = EXCLUDED.config, "
            "created_at = now()",
            (name, kind, json.dumps(config)),
        )
    conn.commit()


def delete_view(conn, name: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM dashboard_saved_views WHERE name = %s", (name,))
    conn.commit()
