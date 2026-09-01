"""
Arithmetic validation for extracted PO data — no external dependencies, so it can be
imported both by the extraction pipeline (extract_pos.py) and the dashboard
(dashboard/app.py, a separate venv that deliberately doesn't have anthropic/pdfplumber).
"""

MATH_TOLERANCE = 0.02    # dollars — floor for arithmetic checks (rounding noise)
MATH_TOLERANCE_PCT = 0.001  # + 0.1% of the larger figure, so big orders don't
                            # false-flag on accumulated per-line rounding


def _tol(*refs) -> float:
    """Absolute tolerance for a comparison: max($0.02, 0.1% of the biggest
    figure involved)."""
    biggest = max((abs(r) for r in refs if r is not None), default=0.0)
    return max(MATH_TOLERANCE, MATH_TOLERANCE_PCT * biggest)


def _n(v):
    """Coerce a possibly string-typed numeric field to float (or None). Callers
    have historically handed this module Decimals (psycopg2 NUMERIC) and strings
    (model tool output typed "12" instead of 12); mixing either with a float in
    one expression raises TypeError, which upstream then mislabels. Coerce here
    so this shared, dependency-free checker never crashes on a caller's typing."""
    if v is None:
        return None
    try:
        return float(str(v).strip().replace("$", "").replace(",", ""))
    except (ValueError, TypeError):
        return None


def validate_math(data: dict) -> None:
    """
    Flags arithmetic mismatches for manual review; does not alter any values.
    Sets item['math_mismatch'] and data['math_check_failed']/['math_check_detail'].
    """
    items = data.get("line_items") or []
    line_total_sum = 0.0
    has_totals = False

    for item in items:
        # Recompute from scratch — clear any stale flag the caller passed in so an
        # edit that fixes the arithmetic actually removes the mismatch (and a
        # tolerance change re-evaluates old rows). validate_math OWNS this field.
        item["math_mismatch"] = None
        qty, price, total = _n(item.get("quantity")), _n(item.get("unit_price")), _n(item.get("line_total"))
        additional = _n(item.get("additional_cost")) or 0
        if qty is not None and price is not None and total is not None:
            has_totals = True
            expected = qty * price + additional
            if abs(expected - total) > _tol(expected, total):
                if additional:
                    item["math_mismatch"] = (
                        f"{qty} × ${price} + ${additional} = ${expected:.2f}, not ${total}"
                    )
                else:
                    item["math_mismatch"] = f"{qty} × ${price} = ${expected:.2f}, not ${total}"
        if total is not None:
            line_total_sum += total

    subtotal, tax, total_amt = _n(data.get("subtotal")), _n(data.get("tax")), _n(data.get("total"))
    issues = []
    if has_totals:
        # Line-item pricing is sometimes tax-inclusive (sums to total) and sometimes
        # not (sums to subtotal) — accept either; only flag if it matches neither.
        matches_subtotal = subtotal is not None and abs(line_total_sum - subtotal) <= _tol(line_total_sum, subtotal)
        matches_total = total_amt is not None and abs(line_total_sum - total_amt) <= _tol(line_total_sum, total_amt)
        if not matches_subtotal and not matches_total and (subtotal is not None or total_amt is not None):
            against = subtotal if subtotal is not None else total_amt
            issues.append(f"line items sum to ${line_total_sum:.2f}, PO shows ${against}")
    if subtotal is not None and tax is not None and total_amt is not None:
        if abs(subtotal + tax - total_amt) > _tol(total_amt):
            issues.append(f"subtotal (${subtotal}) + tax (${tax}) ≠ total (${total_amt})")

    data["math_check_failed"] = bool(issues)
    data["math_check_detail"] = "; ".join(issues)
