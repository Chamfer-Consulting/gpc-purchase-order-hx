"""Settings — product visibility (hidden_products) and saved views
(dashboard_saved_views). Direct SQL on a reused psycopg2 conn; ported from
dashboard/data.py's set_product_hidden / load_saved_views / save_view /
delete_view and dashboard/views/settings.py."""

from __future__ import annotations

import json

import psycopg2.extras


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


def list_views(conn, kind: str, owner: str) -> list[dict]:
    """A user's own saved views for `kind`, plus any legacy shared ones
    (owner = '') migrated from before views were per-user (0007)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, config FROM dashboard_saved_views "
            "WHERE kind = %s AND owner IN (%s, '') ORDER BY created_at",
            (kind, owner),
        )
        return [{"name": n, "config": c} for n, c in cur.fetchall()]


def save_view(conn, kind: str, name: str, config: dict, owner: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dashboard_saved_views (name, kind, config, owner) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (owner, kind, name) DO UPDATE SET config = EXCLUDED.config, created_at = now()",
            (name, kind, json.dumps(config), owner),
        )
    conn.commit()


def delete_view(conn, kind: str, name: str, owner: str) -> None:
    """Only your own view — legacy shared views (owner = '') are read-only."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dashboard_saved_views WHERE kind = %s AND name = %s AND owner = %s",
            (kind, name, owner),
        )
    conn.commit()
