"""
Arithmetic validation for extracted PO data — no external dependencies, so it can be
imported both by the extraction pipeline (extract_pos.py) and the dashboard
(dashboard/app.py, a separate venv that deliberately doesn't have anthropic/pdfplumber).
"""

MATH_TOLERANCE = 0.02    # dollars — arithmetic checks below this are treated as rounding noise


def validate_math(data: dict) -> None:
    """
    Flags arithmetic mismatches for manual review; does not alter any values.
    Sets item['math_mismatch'] and data['math_check_failed']/['math_check_detail'].
    """
    items = data.get("line_items") or []
    line_total_sum = 0.0
    has_totals = False

    for item in items:
        qty, price, total = item.get("quantity"), item.get("unit_price"), item.get("line_total")
        if qty is not None and price is not None and total is not None:
            has_totals = True
            if abs(qty * price - total) > MATH_TOLERANCE:
                item["math_mismatch"] = f"{qty} × ${price} = ${qty * price:.2f}, not ${total}"
        if total is not None:
            line_total_sum += total

    subtotal, tax, total_amt = data.get("subtotal"), data.get("tax"), data.get("total")
    issues = []
    if has_totals:
        # Line-item pricing is sometimes tax-inclusive (sums to total) and sometimes
        # not (sums to subtotal) — accept either; only flag if it matches neither.
        matches_subtotal = subtotal is not None and abs(line_total_sum - subtotal) <= MATH_TOLERANCE
        matches_total = total_amt is not None and abs(line_total_sum - total_amt) <= MATH_TOLERANCE
        if not matches_subtotal and not matches_total and (subtotal is not None or total_amt is not None):
            against = subtotal if subtotal is not None else total_amt
            issues.append(f"line items sum to ${line_total_sum:.2f}, PO shows ${against}")
    if subtotal is not None and tax is not None and total_amt is not None:
        if abs(subtotal + tax - total_amt) > MATH_TOLERANCE:
            issues.append(f"subtotal (${subtotal}) + tax (${tax}) ≠ total (${total_amt})")

    data["math_check_failed"] = bool(issues)
    data["math_check_detail"] = "; ".join(issues)
