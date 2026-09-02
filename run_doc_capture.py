#!/usr/bin/env python3
"""
Headless PDF capture — sweeps purchase orders that are missing their source
documents and pulls them in:

  * po_pdf      — the PDF attachment(s) on the PO's Gmail thread
  * invoice_pdf — the rendered invoice PDF for each confirmed linked invoice
                  (QuickBooks' Print / Save-as-PDF output)

Meant for a scheduled GitHub Action (.github/workflows/doc_capture.yml), run
shortly after the extraction + QuickBooks sync jobs so new POs get their PDFs
within the day. Also runnable by hand. Idempotent — every document is
sha256-deduped, so re-running only fills gaps.

Bytes land inline in po_documents.content, or in Supabase Storage when
SUPABASE_URL + a Supabase key are set.

Environment: DATABASE_URL (required); GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET (for
--sources gmail); QBO_CLIENT_ID / QBO_CLIENT_SECRET / QBO_REDIRECT_URI /
QBO_ENVIRONMENT (for --sources qbo); SUPABASE_URL + SUPABASE_SECRET_KEY (or the
legacy SUPABASE_SERVICE_KEY) for Storage (optional).
"""

import argparse
import logging
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import doc_storage  # noqa: E402
import pipeline_summary  # noqa: E402
import po_doc_capture  # noqa: E402
import qbo_client  # noqa: E402

logger = logging.getLogger("run_doc_capture")

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def _apply_schema(conn) -> None:
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless PO/invoice PDF capture")
    ap.add_argument("--sources", default="gmail,qbo",
                    help="comma-separated: gmail, qbo (default both)")
    ap.add_argument("--limit", type=int, default=200,
                    help="max POs to process per source per run (default 200); "
                         "with --migrate-storage, max documents moved this run")
    ap.add_argument("--migrate-storage", action="store_true",
                    help="one-off: move documents stored inline in Postgres into "
                         "Supabase Storage (needs SUPABASE_URL + a secret key). "
                         "Resumable; re-run until 'remaining' is 0. Skips the capture sweep.")
    ap.add_argument("--log-file", default="run_doc_capture.log")
    args = ap.parse_args()
    _configure_logging(args.log_file)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)

    sources = [s.strip() for s in args.sources.split(",") if s.strip() in ("gmail", "qbo")]
    if not sources and not args.migrate_storage:
        print("no valid --sources (use gmail and/or qbo)", file=sys.stderr)
        sys.exit(2)

    # Supabase's 2025 key model: sb_secret_... replaces the service_role JWT.
    # Accept either env name (both valid until end of 2026).
    supabase_key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    doc_storage.configure(os.environ.get("SUPABASE_URL", ""), supabase_key)
    storage_on = doc_storage.is_enabled()
    logger.info(
        "doc capture starting — sources=%s limit=%d storage=%s%s",
        sources, args.limit, "supabase" if storage_on else "inline",
        " (migrate mode)" if args.migrate_storage else "",
    )

    conn = psycopg2.connect(database_url)
    try:
        _apply_schema(conn)

        if args.migrate_storage:
            if not storage_on:
                logger.error("Supabase Storage is not configured — set SUPABASE_URL and "
                             "SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_KEY).")
                sys.exit(2)
            res = po_doc_capture.migrate_inline_to_storage(conn, limit=args.limit)
            for err in res.get("errors", [])[:20]:
                logger.warning("  %s", err)
            logger.info(
                "storage migration: %d moved, %d failed, %d still inline",
                res["migrated"], res["failed"], res["remaining"],
            )
            if res["failed"]:
                sys.exit(1)
            print("✅ storage migration pass done"
                  + (f" — {res['remaining']} still to move, re-run to continue"
                     if res["remaining"] else " — nothing left inline"))
            return

        if "qbo" in sources and qbo_client.get_connection(conn) is None:
            logger.warning("QuickBooks not connected — skipping the qbo source")
            sources = [s for s in sources if s != "qbo"]

        try:
            out = po_doc_capture.backfill(
                conn,
                sources=sources,
                limit=args.limit,
                captured_by="scheduled",
                gmail_client_id=os.environ.get("GMAIL_CLIENT_ID", ""),
                gmail_client_secret=os.environ.get("GMAIL_CLIENT_SECRET", ""),
            )
        except qbo_client.QBOReauthRequired as e:
            logger.error("QuickBooks connection needs reauthorisation — %s", e)
            pipeline_summary.write("doc_capture", "reauth_required", error=str(e))
            print("\n⚠️  QuickBooks connection expired/revoked — reconnect from the app's "
                  "Settings → QuickBooks page.")
            sys.exit(3)

        for src, r in out.items():
            logger.info(
                "%s: %d PO(s) scanned, %d PDF(s) captured, %d failed, %d remaining",
                src, r["scanned"], r["captured"], r["failed"], r["remaining"],
            )
            for err in r["errors"][:20]:
                logger.warning("  %s", err)

        failed = sum(r["failed"] for r in out.values())
        pipeline_summary.write(
            "doc_capture", "ok" if failed == 0 else "partial",
            failed=failed,
            **{
                src: {k: r[k] for k in ("scanned", "captured", "failed", "remaining")}
                for src, r in out.items()
            },
        )
        logger.info("✅ doc capture done%s.", f" ({failed} PO-level failures)" if failed else "")
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("doc capture failed")
        pipeline_summary.write("doc_capture", "failed", error=f"{type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
