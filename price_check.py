"""
Price-anomaly validation for extracted PO data — no external dependencies, so it can be
imported both by the extraction pipeline (extract_pos.py) and the cloud pipeline
(run_cloud_extraction.py). Mirrors math_check.py's reasoning.
"""

import re

PRICE_TOLERANCE_PCT = 0.10  # flag a line item whose price deviates more than this from its reference

# kept in lockstep with qbo_matcher.normalize_customer, which can't be imported here
# (it pulls in psycopg2 and the dashboard/pipeline venvs must stay light).
_COMMON_SUFFIXES = {"inc", "llc", "co", "company", "produce", "corp", "corporation"}


def normalize_customer(name) -> str:
    """Lowercase, drop punctuation + common legal-entity words — for substring
    comparison so "Steve Testa" and "Testa Produce Inc." resolve to the same account."""
    if not name:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(name).lower())
    return " ".join(w for w in cleaned.split() if w not in _COMMON_SUFFIXES)


def same_customer(a: str | None, b: str | None) -> bool:
    """True if two customer names are the same account — normalised-substring
    either way ("Steve Testa" ⊂ "Steve Testa Produce"; "testa" ⊂ "steve testa")."""
    na, nb = normalize_customer(a), normalize_customer(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


def canonical_customer_map(names) -> dict:
    """{raw name -> canonical display name}, collapsing spelling variants onto the
    longest (most complete) name in each `same_customer` cluster. Greedy — stable
    for the handful of distinct customer names this codebase sees."""
    clusters: list[list[str]] = []
    for n in dict.fromkeys(x for x in names if x):
        for cl in clusters:
            if any(same_customer(n, m) for m in cl):
                cl.append(n)
                break
        else:
            clusters.append([n])
    out: dict = {}
    for cl in clusters:
        display = max(cl, key=len)
        for m in cl:
            out[m] = display
    return out


def _lookup_reference(reference_prices: dict, customer_name: str, product_name, container_size):
    """Reference price for this (customer, product, size). Exact key first, then a
    fuzzy customer match on the same product/size — so a spelling drift in the PO's
    customer name ("Get Fresh" vs "Get Fresh Produce, LLC.") doesn't silently skip
    the check."""
    ref = reference_prices.get((customer_name, product_name, container_size))
    if ref is not None:
        return ref
    return next(
        (
            price
            for (cust, prod, size), price in reference_prices.items()
            if prod == product_name and size == container_size and same_customer(cust, customer_name)
        ),
        None,
    )


def flag_price_anomaly(item: dict, customer_name: str | None, reference_prices: dict) -> None:
    """Flags item['price_anomaly'] if unit_price deviates from the known reference price
    for this (customer, product, size) by more than PRICE_TOLERANCE_PCT. Does not alter
    any values. reference_prices: {(customer_name, product_name, container_size): price}.
    """
    price = item.get("unit_price")
    if price is None or not customer_name:
        return
    try:
        price = float(str(price).strip().replace("$", "").replace(",", ""))
    except (ValueError, TypeError):
        return  # unparseable price — nothing to compare against a reference
    ref = _lookup_reference(
        reference_prices, customer_name, item.get("product_name"), item.get("container_size")
    )
    if not ref:
        return
    deviation = (price - ref) / ref
    if abs(deviation) > PRICE_TOLERANCE_PCT:
        item["price_anomaly"] = (
            f"${price:.2f} vs reference ${ref:.2f} for this customer/product/size ({deviation * 100:+.0f}%)"
        )
