"""Reference prices — the expected price per (customer, product, size) that drives
the price-anomaly flag in Data Quality — plus the unit-price history that informs
an edit. Ported from dashboard/views/reports_pricing.py; written as direct SQL on
a reused psycopg2 conn (no dependency on data.py's self-connecting loaders).

`auto` rows are refreshed from the most recent price actually paid on every
extraction sync. Editing a price (or adding a row) flips it to `manual` +
edited = TRUE, which sync_dashboard.py's publish guard never overwrites."""

from __future__ import annotations

from statistics import median

import psycopg2.extras

from qbo_matcher import customers_match  # shared/, via app.reuse

from . import audit

# Consistent per-product pricing rolled out over ~June–July 2024; before this each
# customer paid a different price, so the history chart shades this transition and
# de-emphasises everything to its left rather than treating the spread as anomalies.
_STD_BAND_START = "2024-06-01"
_STD_BAND_END = "2024-07-31"


def _canonicalise(names: list[str]) -> dict[str, str]:
    """{raw customer name -> display name} collapsing spelling variants ("Testa
    Produce" / "Steve Testa") onto the longest (most complete) name in each
    cluster — same `customers_match` fuzziness the rest of the app uses — so the
    price-history chart draws one line per account."""
    clusters: list[list[str]] = []
    for n in dict.fromkeys(x for x in names if x):
        for cl in clusters:
            if any(customers_match(n, m) for m in cl):
                cl.append(n)
                break
        else:
            clusters.append([n])
    out: dict[str, str] = {}
    for cl in clusters:
        display = max(cl, key=len)
        for m in cl:
            out[m] = display
    return out


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
              AND COALESCE(po.status, 'active') = 'active'
              AND li.product_name NOT IN (SELECT product_name FROM hidden_products)
            ORDER BY li.product_name, li.container_size
            """
        )
        return [dict(r) for r in cur.fetchall()]


def _build_delivery_rates(rate_rows: list[dict], canon: dict[str, str]) -> dict:
    """From per-invoice delivery-per-item rates (delivery $ ÷ product units on
    invoices that itemise delivery), build a cascading median lookup:
    (customer, year) → customer → global. Customer names are canonicalised so a
    PO's spelling resolves to the same bucket."""
    by_cy: dict[tuple[str, int], list[float]] = {}
    by_cust: dict[str, list[float]] = {}
    allr: list[float] = []
    for r in rate_rows:
        rate = r.get("rate")
        if rate is None:
            continue
        rate = float(rate)
        if rate <= 0:
            continue
        name = canon.get(r["customer_name"], r["customer_name"])
        allr.append(rate)
        by_cust.setdefault(name, []).append(rate)
        yr = r.get("yr")
        if yr is not None:
            by_cy.setdefault((name, int(yr)), []).append(rate)
    return {
        "cy": {k: float(median(v)) for k, v in by_cy.items()},
        "cust": {k: float(median(v)) for k, v in by_cust.items()},
        "global": float(median(allr)) if allr else 0.0,
    }


def _delivery_rate(tables: dict, canon_name: str, year: int | None) -> float:
    if year is not None and (canon_name, year) in tables["cy"]:
        return tables["cy"][(canon_name, year)]
    if canon_name in tables["cust"]:
        return tables["cust"][canon_name]
    return tables["global"]


def _monthly_trend(points: list[dict], *, since: str) -> list[dict]:
    """Monthly median of the delivery-adjusted price from `since` onward, oldest
    first. [] if fewer than two months have data."""
    buckets: dict[str, list[float]] = {}
    for p in points:
        d = p.get("date")
        if not d or d < since:
            continue
        buckets.setdefault(d[:7], []).append(p["unit_price_adj"])
    if len(buckets) < 2:
        return []
    return [
        {"date": f"{m}-01", "price": round(float(median(v)), 4)}
        for m, v in sorted(buckets.items())
    ]


def price_history(conn, product_name: str, container_size: str) -> dict:
    """Unit price paid over time for one product/size, one point per PO line, with
    a delivery-adjusted price alongside the raw one and an `era` tag for the
    pre/post pricing-standardization split, plus the current reference prices and a
    standardized-era monthly trend."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT po.id AS po_id, po.po_date::text AS date, po.customer_name,
                   li.unit_price::float AS unit_price
            FROM line_items li
            JOIN purchase_orders po ON po.id = li.po_id
            WHERE li.product_name = %s AND COALESCE(li.container_size, '') = %s
              AND li.unit_price IS NOT NULL
              AND NOT COALESCE(li.is_sample, FALSE)
              AND NOT COALESCE(li.is_removed, FALSE)
              AND NOT COALESCE(li.voided, FALSE)
              AND COALESCE(po.status, 'active') = 'active' AND po.po_date IS NOT NULL
              AND li.product_name NOT IN (SELECT product_name FROM hidden_products)
              -- exact match only: a "(deleted)" hidden entry can't collide with a
              -- live customer's raw PO spelling. Fuzzy variants aren't caught here.
              AND COALESCE(po.customer_name, '') NOT IN (SELECT customer_name FROM hidden_customers)
            ORDER BY po.po_date
            """,
            (product_name, container_size),
        )
        points = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT customer_name, price::float AS price, source
            FROM reference_prices
            WHERE product_name = %s AND COALESCE(container_size, '') = %s
            ORDER BY customer_name
            """,
            (product_name, container_size),
        )
        refs = [dict(r) for r in cur.fetchall()]

        # POs whose confirmed-linked invoice itemises delivery — their PO unit
        # price is already delivery-exclusive, so it needs no adjustment.
        cur.execute(
            """
            SELECT DISTINCT l.po_id
            FROM po_invoice_links l
            JOIN qbo_invoice_items ii ON ii.invoice_id = l.invoice_id
            WHERE l.confirmed = TRUE AND ii.category = 'delivery'
            """
        )
        itemised = {r["po_id"] for r in cur.fetchall()}

        # per-invoice delivery-per-item rate, from invoices that DO itemise it
        cur.execute(
            """
            SELECT inv.customer_name AS customer_name,
                   date_part('year', inv.txn_date)::int AS yr,
                   (SUM(ii.line_total) FILTER (WHERE ii.category = 'delivery'))
                     / NULLIF(SUM(ii.quantity) FILTER (WHERE ii.category = 'product'), 0) AS rate
            FROM qbo_invoices inv
            JOIN qbo_invoice_items ii ON ii.invoice_id = inv.id
            WHERE (inv.private_note IS NULL OR inv.private_note NOT ILIKE '%void%')
            GROUP BY inv.id, inv.customer_name, date_part('year', inv.txn_date)
            HAVING SUM(ii.line_total) FILTER (WHERE ii.category = 'delivery') > 0
               AND SUM(ii.quantity)   FILTER (WHERE ii.category = 'product')  > 0
            """
        )
        rate_rows = [dict(r) for r in cur.fetchall()]

    # collapse customer-name spelling variants so one account = one line / one ref
    canon = _canonicalise(
        [r["customer_name"] for r in points + refs + rate_rows if r["customer_name"]]
    )
    for r in points + refs:
        r["customer_name"] = canon.get(r["customer_name"], r["customer_name"])

    rates = _build_delivery_rates(rate_rows, canon)
    for p in points:
        po_id = p.pop("po_id")
        raw = p["unit_price"]
        p["era"] = "pre" if p["date"] < _STD_BAND_START else "post"
        p["delivery_itemised"] = po_id in itemised
        if p["delivery_itemised"]:
            p["unit_price_adj"] = raw
        else:
            year = int(p["date"][:4]) if p["date"] else None
            rate = _delivery_rate(rates, p["customer_name"], year)
            p["unit_price_adj"] = max(round(raw - rate, 4), 0.01)

    return {
        "product_name": product_name,
        "container_size": container_size,
        "standardization_band": {"start": _STD_BAND_START, "end": _STD_BAND_END},
        "points": points,
        "reference_prices": refs,
        "standardized_trend": _monthly_trend(points, since=_STD_BAND_END),
    }


def save_reference_prices(conn, rows: list[dict], actor: str | None, *, commit: bool = True) -> int:
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
    if commit:
        conn.commit()
    return len(clean)


def delete_reference_prices(conn, keys: list[list[str]], actor: str | None, *, commit: bool = True) -> int:
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
    if commit:
        conn.commit()
    return len(triples)
