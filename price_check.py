"""
Price-anomaly validation for extracted PO data — no external dependencies, so it can be
imported both by the extraction pipeline (extract_pos.py) and the dashboard
(dashboard/app.py, a separate venv). Mirrors math_check.py's reasoning.
"""

PRICE_TOLERANCE_PCT = 0.10  # flag a line item whose price deviates more than this from its reference


def flag_price_anomaly(item: dict, customer_name: str | None, reference_prices: dict) -> None:
    """Flags item['price_anomaly'] if unit_price deviates from the known reference price
    for this (customer, product, size) by more than PRICE_TOLERANCE_PCT. Does not alter
    any values. reference_prices: {(customer_name, product_name, container_size): price}.
    """
    price = item.get("unit_price")
    if price is None or not customer_name:
        return
    ref = reference_prices.get((customer_name, item.get("product_name"), item.get("container_size")))
    if not ref:
        return
    deviation = (price - ref) / ref
    if abs(deviation) > PRICE_TOLERANCE_PCT:
        item["price_anomaly"] = (
            f"${price:.2f} vs reference ${ref:.2f} for this customer/product/size ({deviation * 100:+.0f}%)"
        )
