#!/usr/bin/env python3
"""
Cloud extraction pipeline — pulls new PO/revision emails (attachments and body
text) from labeled Gmail messages and writes straight to Postgres, since a GitHub
Actions runner has no durable local disk to keep a SQLite "source of truth" across
runs the way the local pipeline does (extract_pos.py/db.py/sync_dashboard.py).

Meant to run manually or via a scheduled GitHub Action
(.github/workflows/extract_pos.yml, not yet built — see
/Users/jcaternolo/.claude/plans/golden-soaring-robin.md for the full design).

Usage:
    python run_cloud_extraction.py                 # incremental, since gmail_connection's cursor
    python run_cloud_extraction.py --full-backlog   # ignore the cursor, scan each label's full history
    python run_cloud_extraction.py --limit 5        # cap messages processed (for testing)

Environment:
    ANTHROPIC_API_KEY, DATABASE_URL, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_LABELS
    (GMAIL_LABELS: comma- or newline-separated exact label names, e.g.
    "1. Customers/Get Fresh Produce,1. Customers/Midwest Foods" — see GMAIL_SETUP.md)

Idempotent like the local pipeline: a message/attachment already represented in
Postgres under the same (source_file, file_hash) is skipped without calling Claude
again, so a message that falls within the incremental search window more than once
(or a --full-backlog rerun) doesn't cost anything beyond the Gmail API calls needed
to re-hash it.
"""

import argparse
import hashlib
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone

import anthropic
import psycopg2
from tqdm import tqdm

import gmail_client
import postgres_store
from extract_pos import _extract_from_source, annotate_revisions, extract_pdf_text, pdf_to_base64
from sync_dashboard import _publish_to_postgres  # noqa — same cross-module private-import
# pattern sync_dashboard.py itself already uses for extract_pos.annotate_revisions.

logger = logging.getLogger("run_cloud_extraction")

MAX_SEARCH_RESULTS = 1000  # per label, per run — generous upper bound; --limit trims further for testing

# Matches a PO number referenced in free text, e.g. "PO #417721", "P.O. 00507042",
# "order 434416" — used to detect a shorthand/delta revision email (one that
# describes a change against a prior order rather than restating it) and find that
# prior order as reference context. See EXTRACTION_PROMPT's matching rule.
_PO_NUMBER_REF_PATTERN = re.compile(r"\b(?:P\.?\s?O\.?|order)\s*#?\s*(\d{5,9})\b", re.IGNORECASE)


def configure_logging(log_path: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"❌ {name} environment variable not set", file=sys.stderr)
        sys.exit(1)
    return value


def _parse_labels(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n]", raw) if p.strip()]


def _sniff_po_number(text: str) -> str | None:
    m = _PO_NUMBER_REF_PATTERN.search(text)
    return m.group(1) if m else None


def _format_prior_po_context(prior: dict) -> str:
    lines = [
        "Reference — the most recently known version of the PO this email appears "
        "to reference (see the extraction rules for how to use this):",
        f"PO number: {prior.get('po_number')}",
        f"Customer: {prior.get('customer_name')}",
        f"Total: {prior.get('total')}",
        "Line items:",
    ]
    for item in prior.get("line_items") or []:
        lines.append(
            f"  - {item.get('product_name')} ({item.get('container_size')}): "
            f"qty {item.get('quantity')}, unit price {item.get('unit_price')}, "
            f"line total {item.get('line_total')}"
        )
    lines.append("")
    lines.append("--- New email content follows ---")
    lines.append("")
    return "\n".join(lines)


def _received_at(message: dict) -> str | None:
    raw = message.get("internalDate")
    if not raw:
        return None
    try:
        dt = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _process_message(
    client: anthropic.Anthropic,
    access_token: str,
    message_id: str,
    reference_prices: dict,
    pg_conn,
    stop_event: threading.Event,
) -> list[dict]:
    """Returns extraction result dict(s) for one Gmail message — one per PDF
    attachment if any exist, otherwise a single result from the body text (with
    prior-PO context injected when the message looks like a shorthand delta
    revision — see _sniff_po_number). Already-extracted content is skipped without
    calling Claude — see postgres_store.is_known()."""
    message = gmail_client.get_message(access_token, message_id)
    headers = gmail_client.message_headers(message)
    subject = headers.get("subject", "")
    from_addr = headers.get("from", "")
    date_header = headers.get("date", "")
    body_text, attachments = gmail_client.extract_body_and_attachments(message)
    received_at = _received_at(message)

    results = []

    if attachments:
        for att in attachments:
            if stop_event.is_set():
                break
            pdf_bytes = gmail_client.get_attachment(access_token, message_id, att["attachment_id"])
            file_hash = hashlib.sha256(pdf_bytes).hexdigest()
            source_label = att["filename"]

            if postgres_store.is_known(pg_conn, source_label, file_hash):
                logger.info(f"{source_label}: unchanged since last run — skipping")
                continue

            text = extract_pdf_text(pdf_bytes)
            pdf_b64 = None if text else pdf_to_base64(pdf_bytes)
            result = _extract_from_source(
                client, source_label, stop_event, reference_prices,
                text=text, pdf_b64=pdf_b64, extraction_method="text" if text else "vision",
            )
            if result is not None:
                result["_file_hash"] = file_hash
                result["source_received_at"] = received_at
                results.append(result)
        return results

    if not body_text.strip():
        return []

    source_label = f"gmail:{message_id}"
    file_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

    if postgres_store.is_known(pg_conn, source_label, file_hash):
        logger.info(f"{source_label}: unchanged since last run — skipping")
        return []

    # Customer identity isn't used to scope this lookup: the Gmail label a message
    # was found under doesn't reliably match the customer_name string Claude itself
    # extracted onto prior POs (e.g. a label's display name vs. the name as printed
    # on the actual document), so scoping by it risked silently missing legitimate
    # matches. po_number alone is specific enough in practice (5-9 digits).
    context_block = ""
    candidate_po = _sniff_po_number(f"{subject}\n{body_text}")
    if candidate_po:
        prior = postgres_store.find_latest_po(pg_conn, candidate_po)
        if prior is not None:
            context_block = _format_prior_po_context(prior)

    full_text = f"Subject: {subject}\nFrom: {from_addr}\nDate: {date_header}\n\n{context_block}{body_text}"

    result = _extract_from_source(
        client, source_label, stop_event, reference_prices, text=full_text, extraction_method="text",
    )
    if result is not None:
        result["_file_hash"] = file_hash
        result["source_received_at"] = received_at
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="Extract PO data from labeled Gmail messages into Postgres")
    parser.add_argument("--full-backlog", action="store_true", help="Ignore the last-synced cursor, scan each label's full history")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N messages found (for testing)")
    parser.add_argument("--log-file", default="run_cloud_extraction.log")
    args = parser.parse_args()

    configure_logging(args.log_file)

    anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
    database_url = _require_env("DATABASE_URL")
    gmail_client_id = _require_env("GMAIL_CLIENT_ID")
    gmail_client_secret = _require_env("GMAIL_CLIENT_SECRET")
    labels = _parse_labels(_require_env("GMAIL_LABELS"))

    pg_conn = psycopg2.connect(database_url)
    try:
        connection = gmail_client.get_connection(pg_conn)
        if connection is None:
            print("❌ Not connected to Gmail — connect via the dashboard's ✉️ Email Ingestion page first.", file=sys.stderr)
            sys.exit(1)

        access_token = gmail_client.get_valid_access_token(pg_conn, gmail_client_id, gmail_client_secret)

        since_epoch = None
        if not args.full_backlog and connection.get("last_synced_at"):
            since_epoch = int(connection["last_synced_at"].timestamp())

        sync_started_at = datetime.now(timezone.utc)

        message_ids, seen = [], set()
        for label in labels:
            query = f'label:"{label}"' + (f" after:{since_epoch}" if since_epoch is not None else "")
            ids = gmail_client.search_messages(access_token, query, max_results=MAX_SEARCH_RESULTS)
            new_ids = [mid for mid in ids if mid not in seen]
            seen.update(new_ids)
            message_ids.extend(new_ids)
            print(f"🔎 {label}: {len(ids)} message(s)")

        if args.limit:
            message_ids = message_ids[: args.limit]

        print(f"📧 {len(message_ids)} message(s) to process across {len(labels)} label(s)")

        if not message_ids:
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print("Nothing new — cursor updated, exiting.")
            return

        client = anthropic.Anthropic(api_key=anthropic_api_key)
        reference_prices = postgres_store.get_reference_prices(pg_conn)
        stop_event = threading.Event()

        new_results = []
        errors = 0
        for message_id in tqdm(message_ids, unit="msg", ncols=80):
            if stop_event.is_set():
                break
            try:
                results = _process_message(client, access_token, message_id, reference_prices, pg_conn, stop_event)
            except Exception as e:
                logger.error(f"{message_id}: unexpected error — {e}")
                results = [{
                    "_source_file": f"gmail:{message_id}", "_extraction_method": "unknown",
                    "error": f"{type(e).__name__}: {e}",
                }]
            for r in results:
                if "error" in r:
                    errors += 1
                new_results.append(r)

        if stop_event.is_set():
            print(f"\n⏸️  Paused: ran out of API credits after {len(new_results)} result(s) this run.")
            print("   Add credits and rerun the same command — already-processed messages are skipped automatically.")
            sys.exit(3)

        if not new_results:
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print("No new extractable content found — cursor updated, exiting.")
            return

        print(f"📈 {len(new_results) - errors} extracted successfully, {errors} error(s)")

        print("🔄 Re-annotating revisions across the full dataset...")
        combined = postgres_store.get_full_dataset(pg_conn) + new_results
        combined.sort(key=lambda r: (r.get("po_date") or "9999", r.get("_source_file") or ""))
        annotate_revisions(combined)

        print("💾 Publishing to Postgres...")
        bad_dates = _publish_to_postgres(combined, database_url)
        if bad_dates:
            print(f"⚠️  {len(bad_dates)} invalid date(s) were nulled out:")
            for source_file, field, value in bad_dates:
                print(f"   {source_file}: {field} = '{value}'")

        gmail_client.mark_synced(pg_conn, sync_started_at)
        print(f"✅ Done — {len(new_results)} new/updated result(s) published.")
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
