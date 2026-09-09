"""Canonical customer-name resolution — one company name for a customer, no
matter which buyer / spelling a PO or invoice carried.

The person who emails a PO ("Sean McLaughlin", "David Jedlecki", "Bill & Chris")
is a *buyer* at the company, not the customer. The customer is the company
("Anthony Marano Company", "Midwest Foods", "Skoufis Food Service") — the QBO
customer the invoice is billed to. `customer_aliases(alias_name PK ->
canonical_name)` maps every seen spelling (buyer names included) to that company.

Auto-seeded from confirmed po_invoice_links (PO-side spelling -> the linked
invoice's QBO customer_name); a human re-points / adds mappings in Settings ->
Customers. `canonical_name` is always a company.

Dependency-free (psycopg2 only) so it imports both from shared/data.py (the
pandas analytics pipeline) and the FastAPI services — same pattern as
math_check.py / price_check.py.
"""

import psycopg2


def load_customer_aliases(conn) -> dict[str, str]:
    """{alias_name -> canonical_name}, exactly as stored. Empty dict if the table
    isn't there yet (bare DB) or is unreadable — callers then fall back to the
    raw name, so nothing breaks before the migration/seed lands."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT alias_name, canonical_name FROM customer_aliases")
            return {a: c for a, c in cur.fetchall() if a and c}
    except psycopg2.Error:
        conn.rollback()
        return {}


def _ci_index(alias_map: dict[str, str]) -> dict[str, str]:
    """casefold(alias) -> canonical, for a whitespace/case-insensitive fallback.
    First spelling wins on a collision (rare)."""
    out: dict[str, str] = {}
    for a, c in alias_map.items():
        out.setdefault(" ".join(a.split()).casefold(), c)
    return out


def canonical(name, alias_map: dict[str, str], ci_index: dict[str, str] | None = None) -> str | None:
    """Canonical company name for a raw PO/invoice customer string: exact match,
    then a whitespace/case-insensitive match, else the trimmed input unchanged
    (an unknown customer is still shown, just not folded). None/blank -> None.

    Pass `ci_index` (from `_ci_index`) when calling in a loop / DataFrame.map so
    the case-insensitive pass isn't rebuilt per row."""
    if name is None:
        return None
    s = " ".join(str(name).split())
    if not s:
        return None
    if s in alias_map:
        return alias_map[s]
    idx = ci_index if ci_index is not None else _ci_index(alias_map)
    return idx.get(s.casefold(), s)


def resolver(conn):
    """Convenience: load the map once and return a `f(name) -> canonical` closure
    with the case-insensitive index pre-built. For per-request backend use."""
    amap = load_customer_aliases(conn)
    idx = _ci_index(amap)
    return lambda name: canonical(name, amap, idx)
