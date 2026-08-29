#!/usr/bin/env python3
"""
Headless QuickBooks sync — keeps qbo_invoices / qbo_invoice_items / qbo_items and
the PO<->invoice match links current with zero clicks. Meant for a scheduled
GitHub Action (.github/workflows/qbo_sync.yml); also runnable by hand.

Each run:  sync_items -> sync_invoices -> qbo_matcher.run_matching
Incremental by default (QBO's LastUpdatedTime cursor). A full resync — which also
prunes invoices deleted in QuickBooks — runs on --full-resync, or automatically
once a week with --weekly-full (Sundays), since an incremental pull never sees a
delete.

The Intuit refresh token rotates on every use and lasts ~100 days; running this
daily keeps the connection alive indefinitely. If it can no longer be exchanged
(revoked, or a >100-day gap) the job exits 3 and someone must reconnect from the
dashboard's QuickBooks -> Connection & Sync page.

Environment: DATABASE_URL, QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REDIRECT_URI,
QBO_ENVIRONMENT ("production" | "sandbox").
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qbo_client  # noqa: E402
import qbo_matcher  # noqa: E402

logger = logging.getLogger("run_qbo_sync")

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def _apply_schema(conn) -> None:
    """Run schema.sql (all statements are IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
    so the qbo_* tables + the auto-sync heartbeat columns exist. Kept local rather
    than importing sync_dashboard.apply_schema to avoid pulling in the PDF/vision
    extraction stack for a QuickBooks job."""
    with open(_SCHEMA_PATH) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _configure_logging(path: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(path), logging.StreamHandler(sys.stdout)],
    )


def _record(conn, ok: bool, error: str | None) -> None:
    """Write the sync heartbeat onto qbo_connection (see schema.sql)."""
    try:
        with conn.cursor() as cur:
            if ok:
                cur.execute(
                    "UPDATE qbo_connection SET auto_synced_at = now(), auto_sync_error = NULL"
                )
            else:
                cur.execute(
                    "UPDATE qbo_connection SET auto_sync_error = %s", ((error or "")[:1000],)
                )
        conn.commit()
    except Exception as e:  # never let the heartbeat write mask the real outcome
        logger.warning(f"could not write sync heartbeat: {e}")
        conn.rollback()


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless QuickBooks invoice/item/match sync")
    ap.add_argument("--full-resync", action="store_true", help="ignore the cursor, re-pull everything and prune deletes")
    ap.add_argument("--weekly-full", action="store_true", help="do a full resync only on Sundays, incremental otherwise")
    ap.add_argument("--skip-matching", action="store_true", help="sync only; don't run PO<->invoice matching")
    ap.add_argument("--log-file", default="run_qbo_sync.log")
    args = ap.parse_args()
    _configure_logging(args.log_file)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)

    full_resync = args.full_resync or (args.weekly_full and datetime.now(timezone.utc).weekday() == 6)
    logger.info(f"QBO sync starting — mode={'full resync' if full_resync else 'incremental'}")

    conn = psycopg2.connect(database_url)
    try:
        _apply_schema(conn)

        connection = qbo_client.get_connection(conn)
        if connection is None:
            logger.error("Not connected to QuickBooks — connect from the dashboard first.")
            sys.exit(2)

        try:
            n_items = qbo_client.sync_items(conn)
            logger.info(f"catalog: {n_items} item(s) upserted")

            result = qbo_client.sync_invoices(conn, full_resync=full_resync)
            logger.info(
                f"invoices: {result['synced']} upserted"
                + (f", {result['deleted']} pruned (no longer in QuickBooks)" if result.get("deleted") else "")
            )

            if not args.skip_matching:
                summary = qbo_matcher.run_matching(conn)
                logger.info(f"matching: {summary}")

        except qbo_client.QBOReauthRequired as e:
            logger.error(f"QuickBooks connection needs reauthorisation — {e}")
            _record(conn, ok=False, error=str(e))
            print("\n⚠️  QuickBooks connection expired/revoked — reconnect from the "
                  "dashboard's QuickBooks → Connection & Sync page, then run a full resync.")
            sys.exit(3)

        _record(conn, ok=True, error=None)
        logger.info("✅ QBO sync done.")
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("QBO sync failed")
        try:
            _record(conn, ok=False, error=f"{type(e).__name__}: {e}")
        except Exception:
            pass
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
