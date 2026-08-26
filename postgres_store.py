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

from collections import defaultdict

import psycopg2.extras

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


def is_known(conn, source_file: str, file_hash: str) -> bool:
    """True if this exact (source_file, file_hash) has already been extracted and
    stored — mirrors db.get_cached_result()'s cache-hit check for the local
    pipeline, so re-scanning a Gmail message already processed in a prior
    incremental run doesn't re-call the Claude API for it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM purchase_orders WHERE source_file = %s AND file_hash = %s LIMIT 1",
            (source_file, file_hash),
        )
        return cur.fetchone() is not None


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
