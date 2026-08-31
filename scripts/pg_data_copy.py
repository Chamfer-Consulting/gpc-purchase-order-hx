#!/usr/bin/env python3
"""Copy table DATA from one Postgres database to another over the COPY protocol —
a psycopg2-only stand-in for `pg_dump --data-only | pg_restore` when the client
tools aren't handy. Schema must already exist on the target (run the migrations
first). See docs/REBUILD-SETUP.md §2.

    python scripts/pg_data_copy.py "<source_url>" "<target_url>" [--exclude t1,t2] [--dry-run]

Per table (parents before children so FK checks pass):
  * copies only the columns present in BOTH databases (so dropped/added columns
    on either side are a non-issue),
  * SKIPS a target table that already has rows (safe to re-run),
  * resets the `id` sequence afterward.
"""

from __future__ import annotations

import io
import re
import sys

import psycopg2

# Parents first, then FK children. Tables not listed are appended (still after
# these). qbo_connection / gmail_connection hold OAuth tokens — exclude with
# --exclude if you'd rather reconnect from the app.
LOAD_ORDER = [
    "purchase_orders", "qbo_invoices", "qbo_items", "reference_prices",
    "hidden_products", "qbo_connection", "gmail_connection",
    "gmail_thread_meta", "gmail_thread_state", "extraction_reviews",
    "extraction_snapshots", "dashboard_saved_views",
    "line_items", "qbo_invoice_items", "po_invoice_links",
]

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _q(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unexpected identifier: {name!r}")
    return f'"{name}"'


def _tables(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
        )
        return [r[0] for r in cur.fetchall()]


def _columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def _count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM public.{_q(table)}")
        return cur.fetchone()[0]


def main() -> None:
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    exclude: set[str] = set()
    while "--exclude" in argv:
        i = argv.index("--exclude")
        if i + 1 < len(argv):
            exclude |= {x.strip() for x in argv[i + 1].split(",") if x.strip()}
            del argv[i:i + 2]
        else:
            del argv[i]
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) != 2:
        print(__doc__)
        sys.exit(2)
    src_url, dst_url = pos

    src = psycopg2.connect(src_url, connect_timeout=15)
    dst = psycopg2.connect(dst_url, connect_timeout=15)
    src.set_session(readonly=True, autocommit=True)

    src_tables = set(_tables(src))
    dst_tables = set(_tables(dst))

    ordered = [t for t in LOAD_ORDER if t in src_tables]
    ordered += sorted(src_tables - set(ordered))

    print(f"{'table':<24} {'rows':>10}   note")
    print("-" * 60)
    total = 0
    skipped_missing, skipped_nonempty, excluded = [], [], []

    for t in ordered:
        if t in exclude:
            excluded.append(t)
            print(f"{t:<24} {'—':>10}   excluded")
            continue
        if t not in dst_tables:
            skipped_missing.append(t)
            print(f"{t:<24} {'—':>10}   not on target — skip")
            continue
        if _count(dst, t) > 0:
            skipped_nonempty.append(t)
            print(f"{t:<24} {_count(dst, t):>10,}   target already has rows — skip")
            continue

        cols = [c for c in _columns(src, t) if c in set(_columns(dst, t))]
        if not cols:
            print(f"{t:<24} {'—':>10}   no shared columns — skip")
            continue
        collist = ", ".join(_q(c) for c in cols)

        n = _count(src, t)
        if dry:
            print(f"{t:<24} {n:>10,}   would copy [{', '.join(cols)}]")
            total += n
            continue

        buf = io.BytesIO()
        with src.cursor() as sc:
            sc.copy_expert(f"COPY (SELECT {collist} FROM public.{_q(t)}) TO STDOUT", buf)
        buf.seek(0)
        with dst.cursor() as dc:
            dc.copy_expert(f"COPY public.{_q(t)} ({collist}) FROM STDIN", buf)
            if "id" in cols:
                dc.execute(
                    f"SELECT setval(pg_get_serial_sequence('public.{t}', 'id'), "
                    f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM public.{_q(t)}), 1), true)"
                )
        dst.commit()
        moved = _count(dst, t)
        total += moved
        print(f"{t:<24} {moved:>10,}   copied")

    src.close()
    dst.close()
    print("-" * 60)
    print(f"{'TOTAL rows moved':<24} {total:>10,}")
    if excluded:
        print(f"excluded: {', '.join(excluded)}")
    if skipped_nonempty:
        print(f"skipped (already had rows): {', '.join(skipped_nonempty)}")
    if skipped_missing:
        print(f"skipped (table not on target): {', '.join(skipped_missing)}")


if __name__ == "__main__":
    main()
