"""
Postgres-side counterpart to db.py's SQLite reader, used by the cloud extraction
pipeline (run_cloud_extraction.py) — which writes straight to Postgres and has no
local SQLite database at all, since a GitHub Actions runner has no durable disk to
be a "source of truth" across runs. Produces the exact same in-memory dict shape as
db.get_all_results()/db._row_to_result(), so extract_pos.py's annotate_revisions()
and sync_dashboard.py's _publish_to_postgres() work on it unmodified regardless of
which store a given result came from.

Deliberately no `import streamlit` — this must import cleanly under .venv312 (no
Streamlit installed there), since it's used by a plain CLI script / GitHub Action,
not the dashboard.
"""

import os
import re
from collections import defaultdict

import psycopg2.extras

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
_CLOUD_SCHEMA_MARKERS = re.compile(
    r"-- =====\s*CLOUD-THREAD-SCHEMA \(start\)\s*=====(.*?)-- =====\s*CLOUD-THREAD-SCHEMA \(end\)\s*=====",
    re.DOTALL,
)

_HEADER_COLUMNS = (
    "source_file", "file_hash", "extraction_method", "error",
    "po_number", "po_date", "sent_date", "delivery_date",
    "document_printed_at", "source_received_at",
    "revision_number", "revision_label", "customer_name", "customer_id",
    "subtotal", "tax", "total", "notes",
    "math_check_failed", "math_check_detail",
    "gmail_thread_id",
)

_LINE_ITEM_COLUMNS = (
    "product_raw", "sku", "quantity", "unit_price", "additional_cost", "line_total",
    "product_name", "container_size", "is_sample", "needs_review",
    "math_mismatch", "price_anomaly",
)


def _to_float(v):
    """Postgres NUMERIC columns come back from psycopg2 as decimal.Decimal, not
    float — SQLite's REAL columns (db.py's equivalent reader) come back as plain
    float, and code downstream (price_check.flag_price_anomaly, math_check, the
    dashboard) does arithmetic assuming that. Mixing Decimal and float in the same
    expression raises TypeError (seen live: 'unsupported operand type(s) for -:
    float and decimal.Decimal', when a freshly-extracted float unit_price met a
    Decimal reference price read back from here) rather than silently coercing, so
    every NUMERIC-sourced value gets normalized to float right here at the source."""
    return float(v) if v is not None else None


def _row_to_result(header_row: dict, line_rows: list) -> dict:
    result = {
        "_source_file": header_row["source_file"],
        "_file_hash": header_row["file_hash"],
        "_extraction_method": header_row["extraction_method"],
        "po_number": header_row["po_number"],
        "po_date": str(header_row["po_date"]) if header_row["po_date"] else None,
        "sent_date": header_row["sent_date"],
        "delivery_date": str(header_row["delivery_date"]) if header_row["delivery_date"] else None,
        "document_printed_at": header_row["document_printed_at"],
        "source_received_at": header_row["source_received_at"],
        "revision_number": header_row["revision_number"],
        "revision_label": header_row["revision_label"],
        "customer_name": header_row["customer_name"],
        "customer_id": header_row["customer_id"],
        "subtotal": _to_float(header_row["subtotal"]),
        "tax": _to_float(header_row["tax"]),
        "total": _to_float(header_row["total"]),
        "notes": header_row["notes"],
        "math_check_failed": bool(header_row["math_check_failed"]),
        "math_check_detail": header_row["math_check_detail"],
        "gmail_thread_id": header_row["gmail_thread_id"],
        "line_items": [],
    }
    if header_row["error"] is not None:
        result["error"] = header_row["error"]

    for it in line_rows:
        item = {col: it[col] for col in _LINE_ITEM_COLUMNS}
        item["is_sample"] = bool(item["is_sample"])
        item["needs_review"] = bool(item["needs_review"])
        for field in ("quantity", "unit_price", "additional_cost", "line_total"):
            item[field] = _to_float(item[field])
        result["line_items"].append(item)

    return result


def get_full_dataset(conn) -> list:
    """Returns every purchase_orders row (including past errors, for parity with
    db.get_all_results()) as the same dict shape extract_pos.py/sync_dashboard.py
    already work with — annotate_revisions() and _publish_to_postgres() run over
    this unmodified.

    Ghost 'Removed' line items (is_removed = TRUE, injected by a prior
    annotate_revisions() run) are excluded — mirrors SQLite's line_items table,
    which has no is_removed column at all and is therefore always ghost-free on
    every read; re-including them here would compound ghosts across every run.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT id, {', '.join(_HEADER_COLUMNS)} FROM purchase_orders ORDER BY id")
        headers = cur.fetchall()

        cur.execute(f"SELECT po_id, {', '.join(_LINE_ITEM_COLUMNS)} FROM line_items WHERE is_removed = FALSE")
        line_rows = cur.fetchall()

    items_by_po = defaultdict(list)
    for row in line_rows:
        items_by_po[row["po_id"]].append(row)

    return [_row_to_result(h, items_by_po.get(h["id"], [])) for h in headers]


def get_related_dataset(conn, po_numbers, source_files) -> list:
    """Like get_full_dataset() but only the purchase_orders rows that could be a
    prior version of something in the current flush batch — those sharing a
    po_number or a source_file with it. annotate_revisions() groups by
    `po_number or _source_file`, so this is exactly the history it needs to label
    "Rev N" correctly; every other group in the table is untouched by this flush
    and pulling it would be pure churn.

    Matters operationally, not just for speed: get_full_dataset() streams the whole
    purchase_orders + line_items tables, and a large streamed result over the
    GitHub Actions -> Neon link is what was dying mid-transfer every checkpoint
    ("SSL connection has been closed unexpectedly"). This query returns a handful
    of rows.

    Ghost 'Removed' line items (is_removed = TRUE) are excluded, same as
    get_full_dataset()."""
    po_numbers = sorted({x for x in po_numbers if x})
    source_files = sorted({x for x in source_files if x})
    clauses, params = [], {}
    if po_numbers:
        clauses.append("po_number = ANY(%(pos)s)")
        params["pos"] = po_numbers
    if source_files:
        clauses.append("source_file = ANY(%(srcs)s)")
        params["srcs"] = source_files
    if not clauses:
        return []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, {', '.join(_HEADER_COLUMNS)} FROM purchase_orders "
            f"WHERE {' OR '.join(clauses)} ORDER BY id",
            params,
        )
        headers = cur.fetchall()
        if not headers:
            return []

        ids = [h["id"] for h in headers]
        cur.execute(
            f"SELECT po_id, {', '.join(_LINE_ITEM_COLUMNS)} FROM line_items "
            f"WHERE is_removed = FALSE AND po_id = ANY(%s)",
            (ids,),
        )
        line_rows = cur.fetchall()

    items_by_po = defaultdict(list)
    for row in line_rows:
        items_by_po[row["po_id"]].append(row)

    return [_row_to_result(h, items_by_po.get(h["id"], [])) for h in headers]


NOT_A_PO_ERROR = "not a purchase order"


def is_known(conn, source_file: str, file_hash: str) -> bool:
    """True if this exact (source_file, file_hash) is already handled — a clean
    extraction, or one the model classified 'not a purchase order' (the thread loop
    tracks those separately via gmail_thread_state). A row that recorded a *real*
    failure (expired token, API/credit error, timeout, exception) is NOT considered
    known, so a transient failure is retried on the next run instead of being stuck
    forever — matches db.get_cached_result()'s `error IS NULL` behaviour for the
    local pipeline, plus the not-a-PO carve-out the cloud pipeline needs."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT error FROM purchase_orders WHERE source_file = %s AND file_hash = %s LIMIT 1",
            (source_file, file_hash),
        )
        row = cur.fetchone()
    if row is None:
        return False
    return row[0] is None or row[0] == NOT_A_PO_ERROR


def thread_has_clean_po(conn, thread_id: str) -> bool:
    """True if this Gmail thread already has at least one successfully-extracted
    purchase_orders row (any source_file — a PDF attachment or the thread text).
    Used to decide whether a thread whose attachments were all skipped this run
    should fall back to whole-thread text extraction: if the order was already
    captured from an attachment, re-reading the email body would just double it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM purchase_orders "
            "WHERE gmail_thread_id = %s AND (error IS NULL OR error = '') LIMIT 1",
            (thread_id,),
        )
        return cur.fetchone() is not None


def _cloud_schema_ddl() -> str:
    """The slice of schema.sql the cloud run's thread loop touches before it reaches
    the publish step (which applies the *full* schema.sql via
    sync_dashboard.apply_schema). Applying the whole file at startup instead was
    measurably slower against a cold serverless DB for no benefit.

    Read straight out of schema.sql (between the CLOUD-THREAD-SCHEMA markers) rather
    than hand-copied, so there is exactly one source of truth for those DDL blocks."""
    with open(_SCHEMA_PATH) as f:
        m = _CLOUD_SCHEMA_MARKERS.search(f.read())
    if not m:
        raise RuntimeError(f"CLOUD-THREAD-SCHEMA markers not found in {_SCHEMA_PATH}")
    return m.group(1)


def ensure_cloud_schema(conn) -> None:
    """Create just the table(s)/column the thread loop reads, and one-time-backfill
    gmail_thread_id for existing text-thread rows (source_file is literally
    'gmail-thread:<id>', 13-char prefix). Idempotent; the backfill matches nothing
    once done. Committed immediately."""
    with conn.cursor() as cur:
        cur.execute(_cloud_schema_ddl())
        cur.execute(
            "UPDATE purchase_orders SET gmail_thread_id = substring(source_file FROM 14) "
            "WHERE gmail_thread_id IS NULL AND source_file LIKE 'gmail-thread:%'"
        )
    conn.commit()


def handled_thread_ids(conn) -> set:
    """Thread IDs already fully processed under the current schema — a purchase_orders
    row that carries gmail_thread_id and did NOT record a real failure, or a
    gmail_thread_state row recording the thread as NOT an order. A --full-backlog run
    skips these (no Gmail fetch, no Claude call) so it stays resumable after a timeout
    instead of re-scanning everything from the top every run. Old rows still needing
    the gmail_thread_id backfill (gmail_thread_id IS NULL) are deliberately NOT in this
    set, so they still get processed and stamped.

    Mirrors is_known()'s predicate: a row whose error is a real failure (expired
    token, API/credit error, timeout) is NOT treated as handled, so --full-backlog
    retries it like the incremental path does. Only error IS NULL (clean) or
    error = 'not a purchase order' counts.

    A was_po=TRUE state row is intentionally NOT trusted on its own: it's only valid
    paired with a published purchase_orders row (covered by the first clause). If the
    PO was never published (e.g. a run killed between checkpoint and publish), the
    thread is genuinely unhandled and must be re-processed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT gmail_thread_id FROM purchase_orders
            WHERE gmail_thread_id IS NOT NULL
              AND (error IS NULL OR error = %s)
            UNION
            SELECT thread_id FROM gmail_thread_state WHERE was_po = FALSE
            """,
            (NOT_A_PO_ERROR,),
        )
        return {row[0] for row in cur.fetchall()}


def get_thread_state(conn, thread_id: str) -> dict | None:
    """The gmail_thread_state row for this thread, or None if it's never been fully
    processed. Keys: message_count, last_file_hash, was_po — see the table comment
    in schema.sql and run_cloud_extraction._process_thread for how it's used to
    skip re-extracting a non-PO thread that only gained more non-order chatter."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT message_count, last_file_hash, was_po FROM gmail_thread_state WHERE thread_id = %s",
            (thread_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_thread_state(conn, thread_id: str, message_count: int, last_file_hash: str, was_po: bool) -> None:
    """Record where this thread stands after processing it this run — so next run
    can tell whether it has changed at all (last_file_hash) and, if it grew, how
    many messages are new (message_count) and whether it was ever an order (was_po).
    Committed immediately: a mid-run crash after this point should still leave the
    thread correctly marked as handled."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gmail_thread_state (thread_id, message_count, last_file_hash, was_po, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (thread_id) DO UPDATE SET
                message_count  = EXCLUDED.message_count,
                last_file_hash = EXCLUDED.last_file_hash,
                was_po         = EXCLUDED.was_po,
                updated_at     = now()
            """,
            (thread_id, message_count, last_file_hash, was_po),
        )
    conn.commit()


def upsert_gmail_thread_meta(
    conn,
    thread_id: str,
    *,
    subject: str | None,
    from_addrs: str | None,
    first_message_at: str | None,
    last_message_at: str | None,
    message_count: int,
    attachment_names: str | None,
    url: str | None,
) -> None:
    """Record human-facing metadata for a Gmail thread the cloud pipeline has just
    seen (see the gmail_thread_meta comment in schema.sql). Called every run the
    thread is processed, regardless of whether extraction actually ran, so it
    backfills on its own. Committed immediately."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gmail_thread_meta (
                thread_id, subject, from_addrs, first_message_at, last_message_at,
                message_count, attachment_names, url, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (thread_id) DO UPDATE SET
                subject          = EXCLUDED.subject,
                from_addrs       = EXCLUDED.from_addrs,
                first_message_at = EXCLUDED.first_message_at,
                last_message_at  = EXCLUDED.last_message_at,
                message_count    = EXCLUDED.message_count,
                attachment_names = EXCLUDED.attachment_names,
                url              = EXCLUDED.url,
                updated_at       = now()
            """,
            (thread_id, subject, from_addrs, first_message_at, last_message_at,
             message_count, attachment_names, url),
        )
    conn.commit()


def link_thread_rows(conn, thread_id: str, source_files: list[str]) -> None:
    """Stamp gmail_thread_id onto any purchase_orders row this thread produced that
    doesn't have it yet — the "gmail-thread:<id>" text row and/or each attachment
    filename. Only touches rows where the column is still NULL, so it's a cheap
    no-op once a thread is linked; its point is backfilling rows that predate the
    column. Committed immediately."""
    if not source_files:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE purchase_orders SET gmail_thread_id = %s "
            "WHERE gmail_thread_id IS NULL AND source_file = ANY(%s)",
            (thread_id, source_files),
        )
    conn.commit()


def get_reference_prices(conn) -> dict:
    """Postgres-side equivalent of db.get_reference_prices() — {(customer_name,
    product_name, container_size): price}, read from the already-synced
    reference_prices table (kept fresh by the local pipeline's sync_dashboard.py
    runs; the cloud pipeline only reads it here, never recomputes it)."""
    with conn.cursor() as cur:
        cur.execute("SELECT customer_name, product_name, container_size, price FROM reference_prices")
        rows = cur.fetchall()
    return {(r[0], r[1], r[2]): _to_float(r[3]) for r in rows}
