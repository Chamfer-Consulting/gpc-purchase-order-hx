"""
Matches PO requests (purchase_orders) to QuickBooks invoices (qbo_invoices), so
"requested vs. shipped" can be reported by product and customer.

Primary key: normalized PO number, exact match — confirmed against real production data
(1,124 of 1,188 real PO numbers, 94.6%, have an exact match after normalization against
QBO's "PO Number" custom field). Falls back to a customer+date+amount score for the
remainder, surfaced for manual review rather than auto-decided — some invoices genuinely
have no PO (verbal/standing orders), and some POs genuinely have no invoice yet.
"""

from datetime import date, datetime
import re

from psycopg2.extras import execute_values

DATE_WINDOW_DAYS = 45
AMOUNT_TOLERANCE_PCT = 0.20
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


def _score_candidate(po: dict, inv: dict):
    """None means the candidate is outside acceptable date range — excluded entirely."""
    po_date, inv_date = po.get("_effective_date"), inv.get("txn_date")
    if po_date and inv_date:
        delta_days = abs((inv_date - po_date).days)
        if delta_days > DATE_WINDOW_DAYS:
            return None
        date_score = max(0.0, 1 - delta_days / DATE_WINDOW_DAYS)
    else:
        date_score = 0.3  # unknown date on one side — small neutral credit, not a veto

    po_total, inv_total = po.get("total"), inv.get("total_amt")
    if po_total and inv_total:
        pct_diff = abs(float(inv_total) - float(po_total)) / float(po_total)
        amount_score = 0.0 if pct_diff > AMOUNT_TOLERANCE_PCT else 1 - pct_diff / AMOUNT_TOLERANCE_PCT
    else:
        amount_score = 0.3

    return round(0.5 * date_score + 0.5 * amount_score, 3)


def run_matching(conn) -> dict:
    """Populates po_invoice_links. Idempotent w.r.t. already-decided pairs — never
    re-proposes a (po_id, invoice_id) pair that's already confirmed or rejected."""
    pos = get_latest_pos(conn)
    invoices = _load_invoices(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT po_id, invoice_id FROM po_invoice_links WHERE confirmed OR rejected")
        decided = set(cur.fetchall())

    by_po_number = {}
    for inv in invoices:
        if inv["_voided"] or not inv["_po_number_norm"]:
            continue
        by_po_number.setdefault(inv["_po_number_norm"], []).append(inv)

    new_links = []  # (po_id, invoice_id, match_method, match_score, confirmed)
    auto_matched = ambiguous = 0
    unmatched_pos = []

    for po in pos:
        norm = normalize_po_number(po.get("po_number"))
        candidates = [c for c in by_po_number.get(norm, []) if (po["id"], c["id"]) not in decided] if norm else []
        if len(candidates) == 1:
            new_links.append((po["id"], candidates[0]["id"], "po_number", 1.0, True))
            auto_matched += 1
        elif len(candidates) > 1:
            for c in candidates:
                new_links.append((po["id"], c["id"], "po_number", 0.5, False))
            ambiguous += 1
        else:
            unmatched_pos.append(po)

    non_voided = [inv for inv in invoices if not inv["_voided"]]
    fuzzy_candidates = no_candidates = 0
    for po in unmatched_pos:
        scored = []
        for inv in non_voided:
            if (po["id"], inv["id"]) in decided or not customers_match(po.get("customer_name"), inv.get("customer_name")):
                continue
            score = _score_candidate(po, inv)
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
        conn.commit()

    return {
        "auto_matched": auto_matched,
        "ambiguous_po_number": ambiguous,
        "fuzzy_candidates": fuzzy_candidates,
        "no_candidates": no_candidates,
        "total_pos": len(pos),
    }


def get_needs_review(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.po_id, l.invoice_id, l.match_method, l.match_score,
                   po.po_number, po.customer_name AS po_customer, po.total AS po_total,
                   po.source_file,
                   inv.doc_number, inv.customer_name AS inv_customer,
                   inv.txn_date, inv.total_amt
            FROM po_invoice_links l
            JOIN purchase_orders po ON po.id = l.po_id
            JOIN qbo_invoices inv ON inv.id = l.invoice_id
            WHERE l.confirmed = FALSE AND l.rejected = FALSE
            ORDER BY po.po_number, l.match_score DESC NULLS LAST
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_unlinked_pos(conn) -> list[dict]:
    """Latest-version POs with no candidate link at all (not even an unconfirmed one) —
    for a manual invoice-picker fallback in the UI."""
    pos = get_latest_pos(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT po_id FROM po_invoice_links")
        linked_ids = {r[0] for r in cur.fetchall()}
    return [po for po in pos if po["id"] not in linked_ids]


def confirm_link(conn, po_id: int, invoice_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE po_invoice_links SET confirmed = TRUE, rejected = FALSE "
            "WHERE po_id = %s AND invoice_id = %s",
            (po_id, invoice_id),
        )
        # Any other still-open candidates for this PO are no longer relevant.
        cur.execute(
            "UPDATE po_invoice_links SET rejected = TRUE "
            "WHERE po_id = %s AND invoice_id != %s AND confirmed = FALSE AND rejected = FALSE",
            (po_id, invoice_id),
        )
    conn.commit()


def reject_link(conn, po_id: int, invoice_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE po_invoice_links SET rejected = TRUE WHERE po_id = %s AND invoice_id = %s",
            (po_id, invoice_id),
        )
    conn.commit()


def manual_link(conn, po_id: int, invoice_id: int) -> None:
    with conn.cursor() as cur:
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
    conn.commit()
