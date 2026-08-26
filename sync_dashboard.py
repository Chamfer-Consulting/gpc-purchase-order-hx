#!/usr/bin/env python3
"""
Publish local PO extraction data to the hosted dashboard database (Neon Postgres).

Usage:
    python sync_dashboard.py --db po_data.db

Requires DATABASE_URL in the environment (a Neon connection string). Recomputes
revision labels/diffs across the *entire* local history each run — not just the
most recent extraction batch — so the dashboard reflects every version of every
PO, including ones extracted in earlier runs.
"""

import argparse
import os
import sys
import time
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

import db
from extract_pos import annotate_revisions

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
MAX_ATTEMPTS = 3       # retries on a dropped/reset connection mid-sync
RETRY_DELAY = 5         # seconds between attempts


def _safe_date(value):
    """Returns value if it's a real calendar date in YYYY-MM-DD form, else None.

    Extraction sometimes yields malformed dates (e.g. '2004-13-26' — invalid
    month) since the source field is free text; SQLite accepts anything, but
    Postgres's DATE column correctly rejects it. Null it out rather than
    failing the whole sync.
    """
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        return None


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL environment variable not set", file=sys.stderr)
        print("   Export your Neon connection string first, e.g.:", file=sys.stderr)
        print('   export DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"', file=sys.stderr)
        sys.exit(1)
    return url


def apply_schema(pg_conn) -> None:
    with open(SCHEMA_PATH) as f:
        schema_sql = f.read()
    with pg_conn.cursor() as cur:
        cur.execute(schema_sql)
    pg_conn.commit()


def _publish_to_postgres(results: list, database_url: str) -> list:
    """One attempt at writing results to Postgres — batched via execute_values instead
    of one round trip per row. Raises psycopg2.OperationalError on a dropped connection;
    the caller retries the whole attempt (upserts are idempotent, so safe to redo)."""
    bad_dates = []
    header_rows = []
    for r in results:
        po_date = _safe_date(r.get("po_date"))
        delivery_date = _safe_date(r.get("delivery_date"))
        if r.get("po_date") and po_date is None:
            bad_dates.append((r.get("_source_file"), "po_date", r.get("po_date")))
        if r.get("delivery_date") and delivery_date is None:
            bad_dates.append((r.get("_source_file"), "delivery_date", r.get("delivery_date")))
        header_rows.append((
            r.get("_source_file"), r.get("_file_hash"), r.get("_extraction_method"), r.get("error"),
            r.get("po_number"), po_date, r.get("sent_date"), delivery_date,
            r.get("document_printed_at"), r.get("source_received_at"),
            r.get("revision_number"), r.get("revision_label"),
            bool(r.get("_is_revision", False)), r.get("_version_label"),
            r.get("customer_name"), r.get("customer_id"),
            r.get("subtotal"), r.get("tax"), r.get("total"), r.get("notes"),
            bool(r.get("math_check_failed", False)), r.get("math_check_detail"),
            r.get("gmail_thread_id"),
        ))

    pg_conn = psycopg2.connect(database_url)
    try:
        apply_schema(pg_conn)

        with pg_conn.cursor() as cur:
            returned = execute_values(
                cur,
                """
                INSERT INTO purchase_orders (
                    source_file, file_hash, extraction_method, error,
                    po_number, po_date, sent_date, delivery_date, document_printed_at, source_received_at,
                    revision_number, revision_label, is_revision, version_label,
                    customer_name, customer_id,
                    subtotal, tax, total, notes,
                    math_check_failed, math_check_detail, gmail_thread_id, extracted_at
                ) VALUES %s
                ON CONFLICT (source_file, file_hash) DO UPDATE SET
                    extraction_method   = EXCLUDED.extraction_method,
                    error               = EXCLUDED.error,
                    po_number           = EXCLUDED.po_number,
                    po_date             = EXCLUDED.po_date,
                    sent_date           = EXCLUDED.sent_date,
                    delivery_date       = EXCLUDED.delivery_date,
                    document_printed_at = EXCLUDED.document_printed_at,
                    source_received_at  = EXCLUDED.source_received_at,
                    revision_number     = EXCLUDED.revision_number,
                    revision_label      = EXCLUDED.revision_label,
                    is_revision         = EXCLUDED.is_revision,
                    version_label       = EXCLUDED.version_label,
                    customer_name       = EXCLUDED.customer_name,
                    customer_id         = EXCLUDED.customer_id,
                    subtotal            = EXCLUDED.subtotal,
                    tax                 = EXCLUDED.tax,
                    total               = EXCLUDED.total,
                    notes               = EXCLUDED.notes,
                    math_check_failed   = EXCLUDED.math_check_failed,
                    math_check_detail   = EXCLUDED.math_check_detail,
                    gmail_thread_id     = EXCLUDED.gmail_thread_id,
                    extracted_at        = now()
                WHERE purchase_orders.edited = FALSE
                RETURNING source_file, file_hash, id
                """,
                header_rows,
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                page_size=200,
                fetch=True,
            )

            # Rows absent from `returned` had edited=TRUE and the WHERE guard skipped
            # their update (RETURNING yields nothing for a skipped conflict) — their
            # header AND line items are protected, leave both alone.
            id_lookup = {(row[0], row[1]): row[2] for row in returned}

            po_ids_to_refresh = []
            line_item_rows = []
            for r in results:
                po_id = id_lookup.get((r.get("_source_file"), r.get("_file_hash")))
                if po_id is None:
                    continue
                po_ids_to_refresh.append(po_id)
                for item in r.get("line_items") or []:
                    line_item_rows.append((
                        po_id, item.get("product_raw"), item.get("sku"),
                        item.get("quantity"), item.get("unit_price"), item.get("additional_cost"),
                        item.get("line_total"),
                        item.get("product_name"), item.get("container_size"),
                        bool(item.get("is_sample", False)), bool(item.get("needs_review", False)),
                        item.get("math_mismatch"), item.get("revision_status"),
                        bool(item.get("_removed", False)), item.get("changes"), item.get("price_anomaly"),
                    ))

            if po_ids_to_refresh:
                cur.execute("DELETE FROM line_items WHERE po_id = ANY(%s)", (po_ids_to_refresh,))
            if line_item_rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO line_items (
                        po_id, product_raw, sku, quantity, unit_price, additional_cost, line_total,
                        product_name, container_size, is_sample, needs_review,
                        math_mismatch, revision_status, is_removed, changes, price_anomaly
                    ) VALUES %s
                    """,
                    line_item_rows,
                    page_size=500,
                )

        pg_conn.commit()
    finally:
        pg_conn.close()

    return bad_dates


def _publish_reference_prices(sqlite_path: str, database_url: str) -> int:
    """Publishes local reference_prices to Postgres — 'auto' rows are refreshed every
    sync; rows a user has manually edited in the dashboard (edited=TRUE) are protected
    by the same WHERE-guard idiom as purchase_orders, so this never overwrites them."""
    conn = db.connect(sqlite_path)
    rows = db.get_reference_price_rows(conn)
    conn.close()
    if not rows:
        return 0

    pg_conn = psycopg2.connect(database_url)
    try:
        with pg_conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO reference_prices (customer_name, product_name, container_size, price, source)
                VALUES %s
                ON CONFLICT (customer_name, product_name, container_size) DO UPDATE SET
                    price      = EXCLUDED.price,
                    source     = EXCLUDED.source,
                    updated_at = now()
                WHERE reference_prices.edited = FALSE
                """,
                [(r["customer_name"], r["product_name"], r["container_size"], r["price"], r["source"]) for r in rows],
                page_size=500,
            )
        pg_conn.commit()
    finally:
        pg_conn.close()
    return len(rows)


def publish(sqlite_path: str, database_url: str) -> tuple[int, list]:
    conn = db.connect(sqlite_path)
    results = db.get_all_results(conn)
    conn.close()

    if not results:
        print(f"Nothing to publish — '{sqlite_path}' has no extracted POs yet.")
        return 0, []

    # Recompute revision labels/diffs across the full local history so the
    # dashboard's "Original"/"Rev N" labels stay correct as new data arrives.
    results.sort(key=lambda r: (r.get("po_date") or "9999", r.get("_source_file") or ""))
    annotate_revisions(results)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            bad_dates = _publish_to_postgres(results, database_url)
            _publish_reference_prices(sqlite_path, database_url)
            return len(results), bad_dates
        except psycopg2.OperationalError as e:
            if attempt == MAX_ATTEMPTS:
                raise
            print(
                f"⚠️  Database connection issue (attempt {attempt}/{MAX_ATTEMPTS}): {e}\n   Retrying...",
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY)


def main():
    parser = argparse.ArgumentParser(description="Publish local PO data to the hosted dashboard database")
    parser.add_argument("--db", default="po_data.db", help="Local SQLite database path (default: po_data.db)")
    args = parser.parse_args()

    database_url = get_database_url()
    count, bad_dates = publish(args.db, database_url)
    if count:
        print(f"✅ Published {count} PO record(s) to the dashboard database.")
    if bad_dates:
        print(f"\n⚠️  {len(bad_dates)} invalid date(s) were nulled out (source data had a malformed date):")
        for source_file, field, value in bad_dates:
            print(f"   {source_file}: {field} = '{value}'")


if __name__ == "__main__":
    main()
