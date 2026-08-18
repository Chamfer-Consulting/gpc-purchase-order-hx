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
