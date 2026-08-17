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
from datetime import datetime

import psycopg2

import db
from extract_pos import annotate_revisions

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


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


def publish(sqlite_path: str, database_url: str) -> int:
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

    pg_conn = psycopg2.connect(database_url)
    apply_schema(pg_conn)

    bad_dates = []

    with pg_conn.cursor() as cur:
        for r in results:
            po_date = _safe_date(r.get("po_date"))
            delivery_date = _safe_date(r.get("delivery_date"))
            if r.get("po_date") and po_date is None:
                bad_dates.append((r.get("_source_file"), "po_date", r.get("po_date")))
            if r.get("delivery_date") and delivery_date is None:
                bad_dates.append((r.get("_source_file"), "delivery_date", r.get("delivery_date")))

            cur.execute(
                """
                INSERT INTO purchase_orders (
                    source_file, file_hash, extraction_method, error,
                    po_number, po_date, sent_date, delivery_date,
                    revision_number, revision_label, is_revision, version_label,
                    customer_name, customer_id,
                    subtotal, tax, total, notes,
                    math_check_failed, math_check_detail, extracted_at
                ) VALUES (
                    %(source_file)s, %(file_hash)s, %(extraction_method)s, %(error)s,
                    %(po_number)s, %(po_date)s, %(sent_date)s, %(delivery_date)s,
                    %(revision_number)s, %(revision_label)s, %(is_revision)s, %(version_label)s,
                    %(customer_name)s, %(customer_id)s,
                    %(subtotal)s, %(tax)s, %(total)s, %(notes)s,
                    %(math_check_failed)s, %(math_check_detail)s, now()
                )
                ON CONFLICT (source_file, file_hash) DO UPDATE SET
                    extraction_method = EXCLUDED.extraction_method,
                    error             = EXCLUDED.error,
                    po_number         = EXCLUDED.po_number,
                    po_date           = EXCLUDED.po_date,
                    sent_date         = EXCLUDED.sent_date,
                    delivery_date     = EXCLUDED.delivery_date,
                    revision_number   = EXCLUDED.revision_number,
                    revision_label    = EXCLUDED.revision_label,
                    is_revision       = EXCLUDED.is_revision,
                    version_label     = EXCLUDED.version_label,
                    customer_name     = EXCLUDED.customer_name,
                    customer_id       = EXCLUDED.customer_id,
                    subtotal          = EXCLUDED.subtotal,
                    tax               = EXCLUDED.tax,
                    total             = EXCLUDED.total,
                    notes             = EXCLUDED.notes,
                    math_check_failed = EXCLUDED.math_check_failed,
                    math_check_detail = EXCLUDED.math_check_detail,
                    extracted_at      = now()
                WHERE purchase_orders.edited = FALSE
                RETURNING id
                """,
                {
                    "source_file": r.get("_source_file"),
                    "file_hash": r.get("_file_hash"),
                    "extraction_method": r.get("_extraction_method"),
                    "error": r.get("error"),
                    "po_number": r.get("po_number"),
                    "po_date": po_date,
                    "sent_date": r.get("sent_date"),
                    "delivery_date": delivery_date,
                    "revision_number": r.get("revision_number"),
                    "revision_label": r.get("revision_label"),
                    "is_revision": bool(r.get("_is_revision", False)),
                    "version_label": r.get("_version_label"),
                    "customer_name": r.get("customer_name"),
                    "customer_id": r.get("customer_id"),
                    "subtotal": r.get("subtotal"),
                    "tax": r.get("tax"),
                    "total": r.get("total"),
                    "notes": r.get("notes"),
                    "math_check_failed": bool(r.get("math_check_failed", False)),
                    "math_check_detail": r.get("math_check_detail"),
                },
            )
            row = cur.fetchone()
            if row is not None:
                po_id, was_updated = row[0], True
            else:
                # ON CONFLICT DO UPDATE ... WHERE was false (edited=TRUE) — the row was
                # left untouched and RETURNING yields nothing, so look its id up instead.
                cur.execute(
                    "SELECT id FROM purchase_orders WHERE source_file = %s AND file_hash = %s",
                    (r.get("_source_file"), r.get("_file_hash")),
                )
                po_id, was_updated = cur.fetchone()[0], False

            if not was_updated:
                # Header was protected because it's been manually edited — leave its
                # line items alone too, don't let re-extraction overwrite them.
                continue

            cur.execute("DELETE FROM line_items WHERE po_id = %s", (po_id,))
            for item in r.get("line_items") or []:
                cur.execute(
                    """
                    INSERT INTO line_items (
                        po_id, product_raw, sku, quantity, unit_price, line_total,
                        product_name, container_size, is_sample, needs_review,
                        math_mismatch, revision_status, is_removed, changes
                    ) VALUES (
                        %(po_id)s, %(product_raw)s, %(sku)s, %(quantity)s, %(unit_price)s, %(line_total)s,
                        %(product_name)s, %(container_size)s, %(is_sample)s, %(needs_review)s,
                        %(math_mismatch)s, %(revision_status)s, %(is_removed)s, %(changes)s
                    )
                    """,
                    {
                        "po_id": po_id,
                        "product_raw": item.get("product_raw"),
                        "sku": item.get("sku"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("unit_price"),
                        "line_total": item.get("line_total"),
                        "product_name": item.get("product_name"),
                        "container_size": item.get("container_size"),
                        "is_sample": bool(item.get("is_sample", False)),
                        "needs_review": bool(item.get("needs_review", False)),
                        "math_mismatch": item.get("math_mismatch"),
                        "revision_status": item.get("revision_status"),
                        "is_removed": bool(item.get("_removed", False)),
                        "changes": item.get("changes"),
                    },
                )

    pg_conn.commit()
    pg_conn.close()
    return len(results), bad_dates


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
