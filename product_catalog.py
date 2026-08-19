"""
Product/size/sample normalization — no external dependencies, so it can be imported both
by the extraction pipeline (extract_pos.py) and the dashboard (dashboard/qbo_matcher.py,
a separate venv that deliberately doesn't have anthropic/pdfplumber). Same reasoning as
math_check.py.

Also used to normalize QuickBooks invoice line items (SalesItemLineDetail.ItemRef.name
follows the same "Category:Item - Size" shape as PO line-item text, e.g.
"Bulls Blood Beets:Bulls Blood Beets - 1oz" — the same regexes match it directly).
"""

import re

# Keyword patterns → canonical product name
PRODUCT_PATTERNS = [
    (re.compile(r"rainbow|rbw", re.I),           "Rainbow Mix"),
    (re.compile(r"arugula|rugula",    re.I),      "Arugula"),
    (re.compile(r"cilantro",          re.I),      "Cilantro"),
    (re.compile(r"bull.*blood|bulls.*blood|bull.?s|beets?", re.I), "Bulls Blood Beets"),
    (re.compile(r"basil|genovese",    re.I),      "Genovese Basil"),
    (re.compile(r"broccoli",          re.I),      "Broccoli"),
]

SIZE_PATTERN = re.compile(r"\b(1|2|3|4|8|20)\s*oz\b", re.I)
# Broadened to also match the plural "Samples" (QuickBooks' "Samples & Trials" item
# category) — the original r"\bsamp(le)?\b" fails on "Samples" because the trailing \b
# can't match between the word-char 'e' and the trailing 's'.
SAMPLE_PATTERN = re.compile(r"\bsamp(le)?s?\b", re.I)

# Line items with a unit price above $0 but below this threshold get a
# "needs review" highlight — may be an untagged sample or data error.
SUSPICIOUS_PRICE_THRESHOLD = 5.00

# Non-produce QuickBooks item parents that show up as rare historical one-offs
# (lighting/racking/etc equipment purchases) — not products, not services either.
EQUIPMENT_KEYWORDS = re.compile(r"light|channel|tank|pump|fan|tray|misc material", re.I)


def classify_qbo_item(name: str, item_type: str) -> tuple[str, str, str]:
    """
    Classifies a QuickBooks Item by its full hierarchical name (e.g.
    "Arugula:Arugula - 8oz", "Services:Delivery", "Samples & Trials:Cilantro
    (deleted)") into (category, product_name, container_size).

    category is one of: product | sample | delivery | donation | service | other.
    product_name/container_size are only meaningful for "product"/"sample" —
    tries the existing PRODUCT_PATTERNS first (so e.g. the "Basil" parent still
    resolves to the established "Genovese Basil" canonical name), then falls back
    to the parent segment itself (deleted-item suffix stripped) — this is what
    correctly names every produce line the hardcoded pattern list doesn't know
    about yet, without having to hand-maintain a pattern per product.
    """
    parts = (name or "").split(":")
    parent = parts[0].strip()
    sub = parts[1].strip() if len(parts) > 1 else ""
    parent_lower = parent.lower()

    if SAMPLE_PATTERN.search(parent_lower) or "trial" in parent_lower:
        category = "sample"
    elif parent_lower == "services":
        name_lower = (name or "").lower()
        if "donation" in name_lower:
            category = "donation"
        elif "delivery" in name_lower or "mileage" in name_lower or "freight" in name_lower:
            category = "delivery"
        else:
            category = "service"
    elif EQUIPMENT_KEYWORDS.search(parent_lower):
        category = "other"
    else:
        category = "product"

    product_name = "UNKNOWN"
    for pattern, canon in PRODUCT_PATTERNS:
        if pattern.search(name or ""):
            product_name = canon
            break
    else:
        if category in ("product", "sample"):
            # Prefer the sub-item (the specific product) over the parent, which for
            # grouped items like "Lettuce:Allstar Gourmet Lettuce - 3oz" or
            # "Samples & Trials:Spicy Mix (deleted)" is just a generic bucket name —
            # a single-level item (no colon) has no sub-item, so use the whole name.
            candidate = sub or parent
            candidate = re.sub(r"\s*-\s*\d+\s*oz\.?\s*$", "", candidate, flags=re.I)
            candidate = re.sub(r"\s*\(deleted(-\d+)?\)\s*$", "", candidate, flags=re.I).strip()
            if candidate:
                product_name = candidate

    size_match = SIZE_PATTERN.search(name or "")
    container_size = f"{size_match.group(1)}oz" if size_match else ""

    return category, product_name, container_size


def normalize_product(raw, unit_price=None):
    """
    Returns (canonical_product_name, container_size_string, is_sample, needs_review)
    - is_sample:    confirmed sample (keyword or $0 price)
    - needs_review: price is suspiciously low but not $0 — flag for manual check
    """
    if not raw:
        return "UNKNOWN", "", False, False

    # Detect product
    product = "UNKNOWN"
    for pattern, name in PRODUCT_PATTERNS:
        if pattern.search(raw):
            product = name
            break

    # Detect size
    size_match = SIZE_PATTERN.search(raw)
    size = f"{size_match.group(1)}oz" if size_match else ""

    # Confirmed sample: keyword in description OR price is exactly $0
    is_sample = bool(SAMPLE_PATTERN.search(raw)) or (unit_price is not None and unit_price == 0)

    # Needs review: price exists, non-zero, but suspiciously low
    needs_review = (
        not is_sample
        and unit_price is not None
        and 0 < unit_price < SUSPICIOUS_PRICE_THRESHOLD
    )

    return product, size, is_sample, needs_review
