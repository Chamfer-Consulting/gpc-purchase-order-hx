"""Reference prices — the expected price per (customer, product, size) that drives
the price-anomaly flag in Data Quality — plus the unit-price history that informs
an edit. Ported from dashboard/views/reports_pricing.py; written as direct SQL on
a reused psycopg2 conn (no dependency on data.py's self-connecting loaders).

`auto` rows are refreshed from the most recent price actually paid on every
extraction sync. Editing a price (or adding a row) flips it to `manual` +
edited = TRUE, which sync_dashboard.py's publish guard never overwrites."""

from __future__ import annotations

import psycopg2.extras

from . import audit

_STANDARDIZED = "2024-06-01"  # the pricing-standardization line drawn on the history chart


def list_reference_prices(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, customer_name, product_name, container_size,
                   price::float AS price, source, edited,
                   edited_at, updated_at
            FROM reference_prices
            ORDER BY customer_name, product_name, container_size
            """
        )
        return [
            {
                **dict(r),
                "edited_at": r["edited_at"].isoformat() if r["edited_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in cur.fetchall()
        ]


def price_options(conn) -> list[dict]:
    """(product, size) pairs with priced, non-sample history — the history-chart
    selector. Stable regardless of any date filter."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT li.product_name, li.container_size
            FROM line_items li
            JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.unit_price IS NOT NULL
              AND li.product_name IS NOT NULL AND li.product_name <> 'UNKNOWN'
              AND NOT COALESCE(li.is_sample, FALSE)
              AND NOT COALESCE(li.is_removed, FALSE)
              AND NOT COALESCE(li.voided, FALSE)
              AND po.status = 'active'
              AND li.product_name NOT IN (SELECT product_name FROM hidden_products)
            ORDER BY li.product_name, li.container_size
            """
        )
        return [dict(r) for r in cur.fetchall()]


def price_history(conn, product_name: str, container_size: str) -> dict:
    """Unit price paid over time for one product/size, one point per PO line,
    plus the current reference prices for that selection."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT po.po_date::text AS date, po.customer_name,
                   li.unit_price::float AS unit_price
            FROM line_items li
            JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.product_name = %s AND li.container_size = %s
              AND li.unit_price IS NOT NULL
              AND NOT COALESCE(li.is_sample, FALSE)
              AND NOT COALESCE(li.is_removed, FALSE)
              AND NOT COALESCE(li.voided, FALSE)
              AND po.status = 'active' AND po.po_date IS NOT NULL
            ORDER BY po.po_date
            """,
            (product_name, container_size),
        )
        points = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT customer_name, price::float AS price, source
            FROM reference_prices
            WHERE product_name = %s AND container_size = %s
            ORDER BY customer_name
            """,
            (product_name, container_size),
        )
        refs = [dict(r) for r in cur.fetchall()]

    return {
        "product_name": product_name,
        "container_size": container_size,
        "standardized_on": _STANDARDIZED,
        "points": points,
        "reference_prices": refs,
    }


def save_reference_prices(conn, rows: list[dict], actor: str | None) -> int:
    """Upsert each {customer_name, product_name, container_size, price} as a manual
    override (source='manual', edited=TRUE). Returns the count written."""
    clean: list[dict] = []
    for r in rows:
        cust, prod, size = r.get("customer_name"), r.get("product_name"), r.get("container_size")
        if not (cust and prod and size):
            continue
        try:
            price = float(r["price"])
        except (KeyError, TypeError, ValueError):
            continue
        clean.append({"customer_name": cust, "product_name": prod, "container_size": size, "price": price})

    if not clean:
        return 0

    with conn.cursor() as cur:
        for row in clean:
            cur.execute(
                """
                INSERT INTO reference_prices
                    (customer_name, product_name, container_size, price, source, edited, edited_at)
                VALUES (%(customer_name)s, %(product_name)s, %(container_size)s, %(price)s, 'manual', TRUE, now())
                ON CONFLICT (customer_name, product_name, container_size) DO UPDATE SET
                    price = EXCLUDED.price, source = 'manual', edited = TRUE, edited_at = now(),
                    updated_at = now()
                """,
                row,
            )
    audit.log(conn, actor=actor, action="price_edit", entity="reference_price",
              entity_id=None, after={"rows": clean})
    conn.commit()
    return len(clean)


def delete_reference_prices(conn, keys: list[list[str]], actor: str | None) -> int:
    """Remove rows by [customer_name, product_name, container_size]. An 'auto' row
    removed here comes back on the next sync if a price is still being paid."""
    triples = [tuple(k) for k in keys if isinstance(k, (list, tuple)) and len(k) == 3]
    if not triples:
        return 0
    with conn.cursor() as cur:
        for cust, prod, size in triples:
            cur.execute(
                "DELETE FROM reference_prices WHERE customer_name = %s "
                "AND product_name = %s AND container_size = %s",
                (cust, prod, size),
            )
    audit.log(conn, actor=actor, action="price_delete", entity="reference_price",
              entity_id=None, after={"keys": [list(t) for t in triples]})
    conn.commit()
    return len(triples)
