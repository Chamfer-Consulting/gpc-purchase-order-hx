"""
Matches PO requests (purchase_orders) to QuickBooks invoices (qbo_invoices), so
"requested vs. shipped" can be reported by product and customer.

Primary key: normalized PO number, exact match — confirmed against real production data
(1,124 of 1,188 real PO numbers, 94.6%, have an exact match after normalization against
QBO's "PO Number" custom field). Falls back to a customer+date+amount+line-item score for
the remainder, surfaced for manual review rather than auto-decided — some invoices
genuinely have no PO (verbal/standing orders), and some POs genuinely have no invoice yet.

A PO-number match alone is not treated as absolute certainty: it's corroborated against
customer name (a coincidental PO-number collision across two different customers should
never silently auto-link) and, when a PO number is shared by more than one invoice
(revisions, corrections), against line-item content to pick the real match instead of
guessing.
"""

from datetime import date, datetime
import re
import statistics

from psycopg2.extras import execute_values

DATE_WINDOW_DAYS_DEFAULT = 45   # used until enough confirmed matches exist to calibrate
MIN_SAMPLES_TO_CALIBRATE = 20
AMOUNT_TOLERANCE_PCT = 0.20
AMOUNT_ABS_FLOOR = 10.0          # dollars — protects small orders from pure-percentage math
AMBIGUOUS_ITEM_SIM_THRESHOLD = 0.7   # how good the best candidate's line-item overlap must be
AMBIGUOUS_ITEM_SIM_MARGIN = 0.3      # ...and how much better than the runner-up
MAX_FUZZY_CANDIDATES_PER_PO = 3

_COMMON_SUFFIXES = {"inc", "llc", "co", "company", "produce", "corp", "corporation"}


def normalize_po_number(value) -> str:
    """Digits-only, leading zeros stripped. Empty string if nothing usable is left
    (e.g. QBO's "PO Number" field literally says "Verbal" or "standing" — a genuine
    verbal/standing order with no PO document, not a data-quality problem to fix)."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits.lstrip("0")


def normalize_customer(name) -> str:
    """Lowercase, strip punctuation and common trailing legal-entity words, for
    substring-containment comparison. No fuzzy-matching library needed — only a
    handful of distinct customers exist on either side of this match."""
    if not name:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    words = [w for w in cleaned.split() if w not in _COMMON_SUFFIXES]
    return " ".join(words)


def customers_match(po_customer, qbo_customer) -> bool:
    a, b = normalize_customer(po_customer), normalize_customer(qbo_customer)
    if not a or not b:
        return False
    return a in b or b in a


def confidence_label(match_method: str, score) -> str:
    """Human-readable certainty grade for the review UI."""
    if match_method == "po_number":
        return "Certain (PO number + customer)"
    if match_method == "po_number_items":
        return "Certain (PO number + line items)"
    if match_method == "po_number_ambiguous":
        return "Same PO number on several invoices — pick the right one"
    if match_method == "po_number_review":
        return "PO number matched, but customer doesn't corroborate — verify"
    if match_method == "manual":
        return "Manual"
    if score is None:
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.5:
        return "Medium"
    return "Low"


def is_quick_confirm(confidence: str) -> bool:
    """True for confidence_label() outputs worth a one-click confirm (Certain/High) vs.
    ones that need a full side-by-side look (Medium/Low/ambiguous/customer-mismatch).
    Shared by the Match & Review page's quick-confirm/needs-judgment split and
    dashboard/attention.py's Home digest, so the two surfaces never disagree on what
    counts as "quick"."""
    return confidence.startswith("Certain") or confidence == "High"


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _invoice_po_number(raw_json: dict):
    for field in raw_json.get("CustomField") or []:
        if field.get("Name", "").startswith("PO Number") and "StringValue" in field:
            return field["StringValue"]
    return None


def _is_voided(row: dict) -> bool:
    if not row.get("total_amt"):
        return True
    return "void" in (row.get("private_note") or "").lower()


def get_latest_pos(conn) -> list[dict]:
    """The current (most recent) version of every successfully-extracted PO — same
    dedup logic as dashboard/app.py's prepare(): group by po_number (falling back to
    source_file), keep the row with the latest effective date (sent_date, else po_date)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, po_number, source_file, customer_name, po_date, sent_date, "
            "delivery_date, total FROM purchase_orders WHERE error IS NULL"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    for r in rows:
        r["_effective_date"] = _parse_date(r.get("sent_date")) or r.get("po_date")
        r["_po_key"] = r.get("po_number") or r.get("source_file")

    rows.sort(key=lambda r: (r["_po_key"], r["_effective_date"] or date.min, r["id"]))
    latest = {}
    for r in rows:
        latest[r["_po_key"]] = r  # ascending sort -> last write per key is the latest version
    return list(latest.values())


def search_pos(conn, query: str = "", limit: int = 50, include_matched: bool = False) -> list[dict]:
    """Filters get_latest_pos() by a case-insensitive substring match against PO number,
    customer, or filename — for the manual search-and-match workbench. Filtering in
    Python (not a separate SQL path) since get_latest_pos already loads the full,
    already-deduped PO set fast (<1s over 1188 rows). Already-confirmed POs are excluded
    by default — the point of this search is finding what still needs a decision;
    include_matched=True brings them back for the rare case of reviewing/replacing an
    existing link."""
    pos = sorted(get_latest_pos(conn), key=lambda r: r["_effective_date"] or date.min, reverse=True)
    if not include_matched:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT po_id FROM po_invoice_links WHERE confirmed = TRUE")
            confirmed_ids = {r[0] for r in cur.fetchall()}
        pos = [p for p in pos if p["id"] not in confirmed_ids]
    if query:
        q = query.lower()
        pos = [
            p for p in pos
            if q in (p.get("po_number") or "").lower()
            or q in (p.get("customer_name") or "").lower()
            or q in (p.get("source_file") or "").lower()
        ]
    return pos[:limit]


def _load_invoices(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, qbo_invoice_id, customer_name, txn_date, total_amt, "
            "private_note, raw_json FROM qbo_invoices"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        po_num = _invoice_po_number(r["raw_json"])
        r["_po_number_norm"] = normalize_po_number(po_num)
        r["_voided"] = _is_voided(r)
    return rows


def _po_line_items(conn, po_ids: list[int]) -> dict[int, dict[str, float]]:
    """po_id -> {product_name: total_quantity}, excluding samples/removed rows."""
    if not po_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT po_id, product_name, quantity FROM line_items "
            "WHERE po_id = ANY(%s) AND is_sample = FALSE AND is_removed = FALSE",
            (po_ids,),
        )
        rows = cur.fetchall()
    out: dict[int, dict[str, float]] = {}
    for po_id, product, qty in rows:
        bucket = out.setdefault(po_id, {})
        bucket[product] = bucket.get(product, 0.0) + float(qty or 0)
    return out


def _invoice_line_items(conn, invoice_ids: list[int]) -> dict[int, dict[str, float]]:
    """invoice_id -> {product_name: total_quantity}, excluding samples."""
    if not invoice_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT invoice_id, product_name, quantity FROM qbo_invoice_items "
            "WHERE invoice_id = ANY(%s) AND is_sample = FALSE AND category = 'product'",
            (invoice_ids,),
        )
        rows = cur.fetchall()
    out: dict[int, dict[str, float]] = {}
    for invoice_id, product, qty in rows:
        bucket = out.setdefault(invoice_id, {})
        bucket[product] = bucket.get(product, 0.0) + float(qty or 0)
    return out


def _invoice_product_subtotals(conn, invoice_ids: list[int]) -> dict[int, float]:
    """invoice_id -> sum of its non-sample product line_totals. Used by the amount
    sub-score so a PO total is compared like-for-like against the invoice's product
    lines, not its gross total_amt (which folds in delivery / service / tax lines —
    ~16% of confirmed matches differ enough on gross to score 0 on amount)."""
    if not invoice_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT invoice_id, COALESCE(SUM(line_total), 0) FROM qbo_invoice_items "
            "WHERE invoice_id = ANY(%s) AND is_sample = FALSE AND category = 'product' "
            "GROUP BY invoice_id",
            (invoice_ids,),
        )
        return {inv_id: float(subtotal or 0) for inv_id, subtotal in cur.fetchall()}


def _invoice_amount_for_scoring(inv: dict, inv_subtotals: dict[int, float]):
    """The invoice figure the amount sub-score compares against: its product-line
    subtotal, falling back to gross total_amt when the invoice has no product lines
    (e.g. an all-service invoice — genuinely not a product fulfilment, let the low
    score stand)."""
    return inv_subtotals.get(inv["id"], 0.0) or inv.get("total_amt")


def _line_item_similarity(po_items: dict, inv_items: dict) -> float:
    """Quantity-weighted intersection-over-union across {product: qty} maps.
    1.0 = identical product+quantity sets. 0.0 = no product overlap at all.
    0.5 (no signal either way) only when *both* sides have no line items; if one
    side has products and the other has none they demonstrably don't match, so 0.0
    — otherwise a contentless invoice would outrank a weak-but-real overlap."""
    if not po_items and not inv_items:
        return 0.5
    if not po_items or not inv_items:
        return 0.0
    products = set(po_items) | set(inv_items)
    overlap = sum(min(po_items.get(p, 0.0), inv_items.get(p, 0.0)) for p in products)
    total = sum(max(po_items.get(p, 0.0), inv_items.get(p, 0.0)) for p in products)
    return overlap / total if total else 0.5


def _amount_score(po_total, inv_total) -> float:
    if not po_total or not inv_total:
        return 0.3
    po_total, inv_total = float(po_total), float(inv_total)
    diff = abs(inv_total - po_total)
    tolerance = max(AMOUNT_ABS_FLOOR, po_total * AMOUNT_TOLERANCE_PCT)
    if diff > tolerance:
        return 0.0
    return 1 - diff / tolerance


def _best_date_delta(effective_date, delivery_date, txn_date):
    """Smallest date gap between the invoice date and either PO reference date —
    effective_date (sent_date, else po_date: when the order was placed) or
    delivery_date (when the customer wanted it). Invoices are often generated at or
    near actual delivery rather than at order placement, so delivery_date can be the
    better predictor; take whichever is closer instead of picking just one."""
    if not txn_date:
        return None
    candidates = [d for d in (effective_date, delivery_date) if d]
    if not candidates:
        return None
    return min(abs((txn_date - d).days) for d in candidates)


def _calibrated_date_window(conn) -> int:
    """The ~P95 best observed date gap (see _best_date_delta) across confirmed,
    customer-corroborated PO-number matches, clamped to [14, 90] days — a data-driven
    fuzzy window instead of a guess. Falls back to the default until there are enough
    confirmed matches to trust. For this dataset invoices land the same day as the PO
    (P95 = 0), so the 14-day floor is what actually applies."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT po.sent_date, po.po_date, po.delivery_date, inv.txn_date
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = TRUE AND l.match_method IN ('po_number', 'po_number_items')
            """
        )
        rows = cur.fetchall()
    deltas = []
    for sent_date, po_date, delivery_date, txn_date in rows:
        effective = _parse_date(sent_date) or po_date
        delta = _best_date_delta(effective, delivery_date, txn_date)
        if delta is not None:
            deltas.append(delta)
    if len(deltas) < MIN_SAMPLES_TO_CALIBRATE:
        return DATE_WINDOW_DAYS_DEFAULT
    # Interpolated P95 (statistics.quantiles), not deltas[int(n*0.95)] — the latter
    # degenerates to the single max value at small sample counts.
    p95 = statistics.quantiles(deltas, n=100, method="inclusive")[94] if len(deltas) >= 2 else deltas[0]
    return int(round(max(14, min(90, p95))))


MIN_PO_DIGITS_FOR_HINT = 6


def _po_number_hint_score(po, inv) -> float:
    """1.0 if the PO's number appears as a contiguous digit-substring inside the
    invoice's own PO-number field, even though it didn't match exactly — e.g. an
    EDI-style reference code that embeds the real PO number
    ("047000101004971660001" contains "4971660"), or a transcription typo with an
    extra digit. Length-gated to avoid coincidental hits on short digit runs."""
    po_norm = normalize_po_number(po.get("po_number"))
    inv_norm = inv.get("_po_number_norm")
    if len(po_norm) < MIN_PO_DIGITS_FOR_HINT or not inv_norm or po_norm == inv_norm:
        return 0.0
    return 1.0 if po_norm in inv_norm else 0.0


def _score_candidate(po, inv, po_items_map, inv_items_map, date_window, inv_subtotals=None):
    """None means the candidate is outside the acceptable date range — excluded entirely.
    Line-item content and a possible embedded-PO-number hint are weighted highest
    (0.3, 0.2) since they're the most specific independent signals available once an
    exact PO-number match isn't; date/amount proximity (0.25 each) corroborate."""
    delta_days = _best_date_delta(po.get("_effective_date"), po.get("delivery_date"), inv.get("txn_date"))
    if delta_days is None:
        date_score = 0.3
    elif delta_days > date_window:
        return None
    else:
        date_score = max(0.0, 1 - delta_days / date_window)

    inv_amount = _invoice_amount_for_scoring(inv, inv_subtotals or {})
    amount_score = _amount_score(po.get("total"), inv_amount)
    item_score = _line_item_similarity(po_items_map.get(po["id"], {}), inv_items_map.get(inv["id"], {}))
    hint_score = _po_number_hint_score(po, inv)

    return round(0.25 * date_score + 0.25 * amount_score + 0.3 * item_score + 0.2 * hint_score, 3)


def explain_candidate(conn, po_id: int, invoice_id: int) -> dict | None:
    """Recomputes _score_candidate()'s four weighted sub-scores (date/amount/item-overlap/
    PO-number hint) for one PO<->invoice pair, for display in the Match & Review page's
    score-breakdown popover (dashboard/views/fulfillment_match.py) — reuses the exact same
    helper functions and weights run_matching() uses, so the breakdown shown to a reviewer
    can never drift from what the algorithm actually computed. Purely for display: this
    result is never persisted and never used to decide anything. Returns None if either
    side no longer exists (e.g. deleted between page load and popover open)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, po_number, customer_name, total, po_date, sent_date, delivery_date "
            "FROM purchase_orders WHERE id = %s",
            (po_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        po = dict(zip(cols, row))
        po["_effective_date"] = _parse_date(po.get("sent_date")) or po.get("po_date")

        cur.execute(
            "SELECT id, customer_name, txn_date, total_amt, raw_json FROM qbo_invoices WHERE id = %s",
            (invoice_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        inv = dict(zip(cols, row))
        inv["_po_number_norm"] = normalize_po_number(_invoice_po_number(inv["raw_json"]))

    po_items_map = _po_line_items(conn, [po_id])
    inv_items_map = _invoice_line_items(conn, [invoice_id])
    inv_subtotals = _invoice_product_subtotals(conn, [invoice_id])
    date_window = _calibrated_date_window(conn)

    delta_days = _best_date_delta(po.get("_effective_date"), po.get("delivery_date"), inv.get("txn_date"))
    outside_window = delta_days is not None and delta_days > date_window
    if delta_days is None:
        date_score = 0.3
    elif outside_window:
        date_score = 0.0  # _score_candidate() would exclude this candidate entirely;
                           # shown as 0 here so the breakdown still explains why.
    else:
        date_score = max(0.0, 1 - delta_days / date_window)

    amount_score = _amount_score(po.get("total"), _invoice_amount_for_scoring(inv, inv_subtotals))
    item_score = _line_item_similarity(po_items_map.get(po_id, {}), inv_items_map.get(invoice_id, {}))
    hint_score = _po_number_hint_score(po, inv)

    return {
        "date_score": round(date_score, 3),
        "date_delta_days": delta_days,
        "date_window_days": date_window,
        "outside_date_window": outside_window,
        "amount_score": round(amount_score, 3),
        "item_score": round(item_score, 3),
        "hint_score": round(hint_score, 3),
        "weighted_total": round(0.25 * date_score + 0.25 * amount_score + 0.3 * item_score + 0.2 * hint_score, 3),
    }


# Matches _is_voided()'s logic, as a SQL fragment — an invoice can be voided in
# QuickBooks well after it was first synced/matched, so this is checked live against
# current qbo_invoices data, not decided once at match time.
_VOID_SQL = "(total_amt IS NULL OR total_amt = 0 OR private_note ILIKE '%%void%%')"


def _release_voided_links(conn, *, commit: bool = True) -> dict:
    """A po_invoice_links row (confirmed or still-pending) pointing at an invoice that
    has since been voided in QuickBooks is stale data. Confirmed links are rejected
    (freeing the PO to be rematched within this same run) rather than silently left
    pointing at a dead invoice forever — the exact "PO becomes stagnant" bug reported
    live. Pending candidates are simply pruned — a voided invoice was never a real
    option, no reason to leave it cluttering the review queue."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE po_invoice_links SET confirmed = FALSE, rejected = TRUE
            WHERE confirmed = TRUE
              AND invoice_id IN (SELECT id FROM qbo_invoices WHERE {_VOID_SQL})
            """
        )
        released = cur.rowcount
        cur.execute(
            f"""
            DELETE FROM po_invoice_links
            WHERE confirmed = FALSE AND rejected = FALSE
              AND invoice_id IN (SELECT id FROM qbo_invoices WHERE {_VOID_SQL})
            """
        )
        pruned = cur.rowcount
    if commit:
        conn.commit()
    return {"released": released, "pruned": pruned}


def run_matching(conn) -> dict:
    """Populates po_invoice_links. Idempotent — never re-proposes a (po_id, invoice_id)
    pair that's already confirmed/rejected, and never searches for *new* candidates for
    a PO that already has a confirmed match (a PO is done once resolved, even though the
    per-pair "decided" filter alone would otherwise let it accumulate spurious extra
    fuzzy candidates against other invoices). Symmetrically, an invoice already confirmed
    to some PO is excluded from every other PO's candidate pool entirely — one invoice
    should back at most one PO, and without this an already-matched invoice could still
    surface as a weak "Low" fuzzy suggestion for a completely unrelated PO that merely
    shares its customer (seen live: an invoice correctly confirmed to PO 471441 was also
    being offered to PO 471105, a different order for the same customer).

    Starts by releasing any link — confirmed or pending — that points at an invoice
    since voided in QuickBooks (see _release_voided_links), so a freshly-released PO is
    reconsidered for a real match in the same run rather than needing a second click.

    The voided-link release, the new-candidate INSERT and the decisive-winner
    sibling rejection all commit together in one transaction at the end — a crash
    mid-run leaves the DB untouched rather than half-applied."""
    voided_summary = _release_voided_links(conn, commit=False)

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT po_id FROM po_invoice_links WHERE confirmed = TRUE")
        already_resolved_po_ids = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT invoice_id FROM po_invoice_links WHERE confirmed = TRUE")
        already_confirmed_invoice_ids = {r[0] for r in cur.fetchall()}

    all_pos = get_latest_pos(conn)
    pos = [po for po in all_pos if po["id"] not in already_resolved_po_ids]
    invoices = [inv for inv in _load_invoices(conn) if inv["id"] not in already_confirmed_invoice_ids]
    po_items_map = _po_line_items(conn, [po["id"] for po in pos])
    inv_items_map = _invoice_line_items(conn, [inv["id"] for inv in invoices])
    inv_subtotals = _invoice_product_subtotals(conn, [inv["id"] for inv in invoices])
    date_window = _calibrated_date_window(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT po_id, invoice_id FROM po_invoice_links WHERE confirmed OR rejected")
        decided = set(cur.fetchall())

    by_po_number = {}
    for inv in invoices:
        if inv["_voided"] or not inv["_po_number_norm"]:
            continue
        by_po_number.setdefault(inv["_po_number_norm"], []).append(inv)

    new_links = []  # (po_id, invoice_id, match_method, match_score, confirmed)
    auto_matched = ambiguous = customer_mismatch = 0
    unmatched_pos = []
    decisive_winners = []  # (po_id, winner_invoice_id) — their losing siblings get rejected post-insert

    for po in pos:
        norm = normalize_po_number(po.get("po_number"))
        raw_candidates = [c for c in by_po_number.get(norm, []) if (po["id"], c["id"]) not in decided] if norm else []
        # Only same-customer invoices are real candidates — a PO-number digit collision
        # across customers must not become review-queue noise. Keep the cross-customer
        # hits aside so a genuine coincidental collision still gets flagged.
        candidates = [c for c in raw_candidates if customers_match(po.get("customer_name"), c.get("customer_name"))]
        cross_customer = [c for c in raw_candidates if c not in candidates]

        if len(candidates) == 1:
            new_links.append((po["id"], candidates[0]["id"], "po_number", 1.0, True))
            auto_matched += 1
        elif len(candidates) > 1:
            # Same PO number on multiple invoices for this customer (revisions/
            # corrections) — use line-item content to pick the real match instead of
            # guessing or dumping all of them into review.
            scored = [
                (_line_item_similarity(po_items_map.get(po["id"], {}), inv_items_map.get(c["id"], {})), c)
                for c in candidates
            ]
            scored.sort(key=lambda x: -x[0])
            best_sim, best_inv = scored[0]
            runner_up_sim = scored[1][0] if len(scored) > 1 else 0.0
            decisive = (
                best_sim >= AMBIGUOUS_ITEM_SIM_THRESHOLD
                and (best_sim - runner_up_sim) >= AMBIGUOUS_ITEM_SIM_MARGIN
            )
            if decisive:
                new_links.append((po["id"], best_inv["id"], "po_number_items", best_sim, True))
                for sim, c in scored[1:]:
                    new_links.append((po["id"], c["id"], "po_number_ambiguous", round(sim, 3), False))
                decisive_winners.append((po["id"], best_inv["id"]))
                auto_matched += 1
            else:
                # A real tie — keep every candidate for the reviewer, but as
                # 'po_number_ambiguous' (not 'po_number') so confidence_label doesn't
                # call an unresolved tie "Certain" and drop it in Quick confirm.
                for sim, c in scored:
                    new_links.append((po["id"], c["id"], "po_number_ambiguous", round(sim, 3), False))
                ambiguous += 1
        elif cross_customer:
            # PO number matched invoice(s), but only for a different customer — flag
            # the most content-similar one for a human rather than silently dropping it.
            flagged = max(
                cross_customer,
                key=lambda c: _line_item_similarity(po_items_map.get(po["id"], {}), inv_items_map.get(c["id"], {})),
            )
            new_links.append((po["id"], flagged["id"], "po_number_review", 0.6, False))
            customer_mismatch += 1
        else:
            unmatched_pos.append(po)

    non_voided = [inv for inv in invoices if not inv["_voided"]]
    fuzzy_candidates = no_candidates = 0
    for po in unmatched_pos:
        scored = []
        for inv in non_voided:
            if (po["id"], inv["id"]) in decided or not customers_match(po.get("customer_name"), inv.get("customer_name")):
                continue
            score = _score_candidate(po, inv, po_items_map, inv_items_map, date_window, inv_subtotals)
            if score is not None:
                scored.append((score, inv))
        scored.sort(key=lambda x: -x[0])
        top = scored[:MAX_FUZZY_CANDIDATES_PER_PO]
        if not top:
            no_candidates += 1
        for score, inv in top:
            new_links.append((po["id"], inv["id"], "fuzzy", score, False))
            fuzzy_candidates += 1

    if new_links:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO po_invoice_links (po_id, invoice_id, match_method, match_score, confirmed)
                VALUES %s
                ON CONFLICT (po_id, invoice_id) DO NOTHING
                """,
                new_links,
            )
            # A PO auto-resolved by line-item disambiguation is done — reject its
            # losing same-number siblings (and any stale pending fuzzy rows) so they
            # don't linger in the review queue.
            for po_id, winner_inv in decisive_winners:
                cur.execute(
                    "UPDATE po_invoice_links SET rejected = TRUE "
                    "WHERE po_id = %s AND invoice_id <> %s AND confirmed = FALSE AND rejected = FALSE",
                    (po_id, winner_inv),
                )
    # One commit for the whole run (release + inserts + sibling rejects).
    conn.commit()

    return {
        "auto_matched": auto_matched,
        "already_resolved": len(already_resolved_po_ids),
        "ambiguous_po_number": ambiguous,
        "customer_mismatch": customer_mismatch,
        "fuzzy_candidates": fuzzy_candidates,
        "no_candidates": no_candidates,
        "total_pos": len(all_pos),
        "date_window_days": date_window,
        "voided_released": voided_summary["released"],
        "voided_pruned": voided_summary["pruned"],
    }


def get_needs_review(conn) -> list[dict]:
    """Full header detail for both sides (not just a summary) — the review UI needs
    enough here to render a real side-by-side comparison, not a one-line guess."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.po_id, l.invoice_id, l.match_method, l.match_score,
                   po.po_number, po.customer_name AS po_customer, po.total AS po_total,
                   po.subtotal AS po_subtotal, po.tax AS po_tax,
                   po.po_date, po.sent_date, po.delivery_date, po.notes AS po_notes,
                   po.source_file,
                   inv.qbo_invoice_id, inv.doc_number, inv.customer_name AS inv_customer,
                   inv.txn_date, inv.due_date, inv.total_amt, inv.private_note AS inv_note
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = FALSE AND l.rejected = FALSE
            ORDER BY po.po_number, l.match_score DESC NULLS LAST
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_line_items_for_review(conn, po_ids: list[int], invoice_ids: list[int]):
    """Batch-fetches full line-item detail for every PO/invoice appearing in the
    needs-review queue — two queries total, not one per candidate, so the review UI
    can render dozens of side-by-side comparisons without a query storm."""
    po_items: dict[int, list[dict]] = {}
    if po_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT po_id, product_name, container_size, quantity, unit_price, "
                "line_total, is_sample FROM line_items "
                "WHERE po_id = ANY(%s) AND is_removed = FALSE ORDER BY id",
                (po_ids,),
            )
            cols = [d[0] for d in cur.description][1:]
            for row in cur.fetchall():
                po_items.setdefault(row[0], []).append(dict(zip(cols, row[1:])))

    inv_items: dict[int, list[dict]] = {}
    if invoice_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT invoice_id, product_name, container_size, quantity, unit_price, "
                "line_total, is_sample, category FROM qbo_invoice_items "
                "WHERE invoice_id = ANY(%s) ORDER BY id",
                (invoice_ids,),
            )
            cols = [d[0] for d in cur.description][1:]
            for row in cur.fetchall():
                inv_items.setdefault(row[0], []).append(dict(zip(cols, row[1:])))

    return po_items, inv_items


def search_invoices(
    conn, customer: str = "", query: str = "", date_from=None, date_to=None,
    amount_min=None, amount_max=None, include_voided: bool = False,
    include_matched: bool = False, limit: int = 100,
) -> list[dict]:
    """Server-side filtered invoice search for the manual search-and-match workbench —
    unlike PO search, qbo_invoices is bigger and range filters (date/amount) belong in
    SQL, not fetched-then-filtered in Python. Already-confirmed invoices are excluded by
    default — an invoice already backing a PO shouldn't clutter the search for a
    different one; include_matched=True brings them back for the rare override case."""
    clauses = []
    params: dict = {}
    if not include_voided:
        clauses.append("total_amt IS NOT NULL AND total_amt != 0")
        clauses.append("(private_note IS NULL OR private_note NOT ILIKE '%%void%%')")
    if not include_matched:
        clauses.append("id NOT IN (SELECT invoice_id FROM po_invoice_links WHERE confirmed = TRUE)")
    if customer:
        clauses.append("customer_name ILIKE %(customer)s")
        params["customer"] = f"%{customer}%"
    if query:
        clauses.append("doc_number ILIKE %(query)s")
        params["query"] = f"%{query}%"
    if date_from:
        clauses.append("txn_date >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        clauses.append("txn_date <= %(date_to)s")
        params["date_to"] = date_to
    if amount_min is not None:
        clauses.append("total_amt >= %(amount_min)s")
        params["amount_min"] = amount_min
    if amount_max is not None:
        clauses.append("total_amt <= %(amount_max)s")
        params["amount_max"] = amount_max

    where = " AND ".join(clauses) if clauses else "TRUE"
    params["limit"] = limit
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, doc_number, customer_name, txn_date, total_amt FROM qbo_invoices "
            f"WHERE {where} ORDER BY txn_date DESC NULLS LAST LIMIT %(limit)s",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_po_full_detail(conn, po_id: int) -> dict:
    """Single-PO header + line items, for the search-and-match workbench's detail pane."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT po_number, source_file, customer_name, po_date, sent_date, "
            "delivery_date, subtotal, tax, total, notes "
            "FROM purchase_orders WHERE id = %s",
            (po_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No purchase order with id={po_id}")
        detail = dict(zip(cols, row))
    po_items, _ = get_line_items_for_review(conn, [po_id], [])
    detail["items"] = po_items.get(po_id, [])
    return detail


def get_invoice_full_detail(conn, invoice_id: int) -> dict:
    """Single-invoice header + line items, for the search-and-match workbench's detail pane."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT qbo_invoice_id, doc_number, customer_name, txn_date, due_date, "
            "total_amt, private_note FROM qbo_invoices WHERE id = %s",
            (invoice_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No QuickBooks invoice with id={invoice_id}")
        detail = dict(zip(cols, row))
    _, inv_items = get_line_items_for_review(conn, [], [invoice_id])
    detail["items"] = inv_items.get(invoice_id, [])
    return detail


def get_confirmed_invoices_for_po(conn, po_id: int) -> list[dict]:
    """Any invoice(s) currently confirmed to this PO — used by the workbench to warn
    before creating a second confirmed link, and to drive the replace_existing option."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT inv.id, inv.doc_number, inv.total_amt FROM po_invoice_links l
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.po_id = %s AND l.confirmed = TRUE
            """,
            (po_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_confirmed_po_for_invoice(conn, invoice_id: int) -> dict | None:
    """The PO this invoice is currently confirmed to, if any — used by the workbench to
    warn before confirming the same invoice against a second, different PO."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT po.id, po.po_number, po.source_file FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            WHERE l.invoice_id = %s AND l.confirmed = TRUE
            LIMIT 1
            """,
            (invoice_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "po_number": row[1], "source_file": row[2]}


def get_unlinked_pos(conn) -> list[dict]:
    """Latest-version POs with no CONFIRMED link — either no candidate was ever proposed,
    or every proposed candidate got rejected. Both cases need the manual-link fallback to
    find them; keying this off "has any link row at all" (the earlier version) missed the
    second case entirely — a PO whose every candidate was rejected would silently vanish
    from both the review queue and this fallback, with no way left to resolve it."""
    pos = get_latest_pos(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT po_id FROM po_invoice_links WHERE confirmed = TRUE")
        confirmed_ids = {r[0] for r in cur.fetchall()}
    return [po for po in pos if po["id"] not in confirmed_ids]


def confirm_link(conn, po_id: int, invoice_id: int, *, commit: bool = True) -> bool:
    """Returns False if no (po_id, invoice_id) link row exists — the caller should
    404 rather than report a silent success."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE po_invoice_links SET confirmed = TRUE, rejected = FALSE "
            "WHERE po_id = %s AND invoice_id = %s",
            (po_id, invoice_id),
        )
        hit = cur.rowcount > 0
        # Any other still-open candidates for this PO are no longer relevant.
        cur.execute(
            "UPDATE po_invoice_links SET rejected = TRUE "
            "WHERE po_id = %s AND invoice_id != %s AND confirmed = FALSE AND rejected = FALSE",
            (po_id, invoice_id),
        )
    if commit:
        conn.commit()
    return hit


def reject_link(conn, po_id: int, invoice_id: int, *, commit: bool = True) -> bool:
    """Returns False if no such link row exists."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE po_invoice_links SET rejected = TRUE WHERE po_id = %s AND invoice_id = %s",
            (po_id, invoice_id),
        )
        hit = cur.rowcount > 0
    if commit:
        conn.commit()
    return hit


def manual_link(conn, po_id: int, invoice_id: int, replace_existing: bool = False,
                *, commit: bool = True) -> None:
    """Links a PO to an invoice directly (the search-and-match workbench, or the older
    single-candidate fallback). Always clears the PO's other still-*pending* candidates —
    a decision has been made, they're no longer relevant. A PO that already has a
    *confirmed* link is left alone by default (multiple invoices per PO is sometimes
    correct — partial shipments) unless replace_existing=True, in which case its other
    confirmed link(s) are rejected first so this becomes the sole one."""
    with conn.cursor() as cur:
        if replace_existing:
            cur.execute(
                "UPDATE po_invoice_links SET confirmed = FALSE, rejected = TRUE "
                "WHERE po_id = %s AND invoice_id != %s AND confirmed = TRUE",
                (po_id, invoice_id),
            )
        cur.execute(
            """
            INSERT INTO po_invoice_links (po_id, invoice_id, match_method, match_score, confirmed)
            VALUES (%s, %s, 'manual', NULL, TRUE)
            ON CONFLICT (po_id, invoice_id) DO UPDATE SET
                confirmed = TRUE, rejected = FALSE, match_method = 'manual'
            """,
            (po_id, invoice_id),
        )
        cur.execute(
            "UPDATE po_invoice_links SET rejected = TRUE "
            "WHERE po_id = %s AND invoice_id != %s AND confirmed = FALSE AND rejected = FALSE",
            (po_id, invoice_id),
        )
    if commit:
        conn.commit()
