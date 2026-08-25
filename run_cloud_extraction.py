#!/usr/bin/env python3
"""
Cloud extraction pipeline — pulls new PO/revision emails from labeled Gmail threads
and writes straight to Postgres, since a GitHub Actions runner has no durable local
disk to keep a SQLite "source of truth" across runs the way the local pipeline does
(extract_pos.py/db.py/sync_dashboard.py).

The unit of work is the Gmail *thread*, not the individual message — most
customers negotiate orders as live back-and-forth email rather than sending a PDF
purchase order, so a thread with no PDF attachment anywhere in it gets extracted
once as a whole labeled conversation (see _process_thread/_build_thread_text),
capturing the final agreed order after the full exchange rather than one message's
isolated, possibly-superseded content. A thread that does carry a PDF attachment
(on any message in it) still extracts each attachment independently, same as a
local PDF file.

Meant to run manually or via a scheduled GitHub Action
(.github/workflows/extract_pos.yml — see
/Users/jcaternolo/.claude/plans/golden-soaring-robin.md for the full design).

Usage:
    python run_cloud_extraction.py                 # incremental, since gmail_connection's cursor
    python run_cloud_extraction.py --full-backlog   # ignore the cursor, scan each label's full history
    python run_cloud_extraction.py --limit 5        # cap threads processed (for testing)

Environment:
    ANTHROPIC_API_KEY, DATABASE_URL, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_LABELS
    (GMAIL_LABELS: comma- or newline-separated exact label names, e.g.
    "1. Customers/Get Fresh Produce,1. Customers/Midwest Foods" — see GMAIL_SETUP.md)

Idempotent like the local pipeline: content already represented in Postgres under
the same (source_file, file_hash) is skipped without calling Claude again — for a
text-only thread, source_file is a stable f"gmail-thread:{thread_id}" and file_hash
is a hash of the whole thread's combined content, so a thread that gains a new
message naturally produces a new hash (and thus a new "revision" row) next run,
while an unchanged thread costs nothing beyond the Gmail API call needed to re-hash
it.
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

MAX_SEARCH_RESULTS = 3000  # per label, per run — customer labels are general
# correspondence (every email exchanged with that customer, not just POs), and
# real per-label volume has been observed as high as ~2,470 for one customer.
# Deliberately no subject-keyword filter: different customers use wildly different,
# idiosyncratic subject conventions for their real orders (e.g. one customer's
# genuine recurring orders are titled "LUCSA <date>", with no mention of
# "purchase"/"order"/"po" at all) — a generic keyword filter would silently drop
# real POs for some customers while barely reducing volume for others. Every
# message under a configured label gets processed; Claude's own is_po
# classification (see _extract_from_source) is what actually screens out non-PO
# correspondence, at the cost of a wasted call per non-PO message rather than the
# risk of a missed real one.

GARFIELD_DOMAIN = "@garfieldproduce.com"  # used to label each message in a
# text-only thread as "us" vs "the customer" — see _sender_label().


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


def _received_at(message: dict) -> str | None:
    raw = message.get("internalDate")
    if not raw:
        return None
    try:
        dt = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _thread_received_at(messages: list) -> str | None:
    """Latest message's timestamp across a whole thread."""
    timestamps = [t for t in (_received_at(m) for m in messages) if t]
    return max(timestamps) if timestamps else None


# Matches the start of an inline quoted prior message — Gmail's "On <date> <sender>
# wrote:" or Outlook's "From: ... Sent: ... To: ... Subject: ..." header block.
# Everything from this point onward in a reply's body is a repeat of a message this
# thread's own combined text already includes once from that earlier message's own
# extraction — left in place, a thread's total text roughly squares with its message
# count for no benefit (verified live: a real 14-message thread's later replies were
# each carrying every earlier message's full signature block via inline quoting).
_QUOTE_BOUNDARY_PATTERN = re.compile(r"(^On .{0,100} wrote:\s*$)|(^From:.*$)", re.MULTILINE)


def _strip_quoted_reply(body_text: str) -> str:
    m = _QUOTE_BOUNDARY_PATTERN.search(body_text)
    return body_text[: m.start()].rstrip() if m else body_text.rstrip()


def _sender_label(from_header: str) -> str:
    """"GARFIELD PRODUCE / US" for our own domain, "CUSTOMER" otherwise — lets the
    model tell our own availability replies apart from what the customer actually
    asked for/confirmed in a multi-message thread. Verified live against a real
    thread: a clean, unambiguous split (orders@garfieldproduce.com vs a customer's
    own domain)."""
    return "GARFIELD PRODUCE / US" if GARFIELD_DOMAIN in (from_header or "").lower() else "CUSTOMER"


def _build_thread_text(messages: list) -> str:
    """Combines every message in a thread into one chronological, sender-labeled
    text block for a single extraction call — see EXTRACTION_PROMPT's rule on
    reading a labeled thread as a live negotiation rather than a static document.
    messages must already be in chronological order (get_thread() returns them
    that way)."""
    blocks = []
    for m in messages:
        headers = gmail_client.message_headers(m)
        from_addr = headers.get("from", "")
        body_text, _ = gmail_client.extract_body_and_attachments(m)
        body_text = _strip_quoted_reply(body_text)
        blocks.append(f"[{headers.get('date', '')}] {_sender_label(from_addr)} ({from_addr}):\n{body_text}")
    return "\n\n---\n\n".join(blocks)


def _process_thread(
    client: anthropic.Anthropic,
    access_token: str,
    thread_id: str,
    reference_prices: dict,
    pg_conn,
    stop_event: threading.Event,
) -> list[dict]:
    """Returns extraction result dict(s) for one Gmail thread, routed by whether
    any message in it carries a PDF attachment:
    - Any PDF attachment anywhere in the thread -> extract each one independently,
      same as extracting a local PDF file, gathered from every message in the
      thread (not just whichever one label search happened to match).
    - No PDF anywhere -> extract once for the WHOLE thread as a single labeled
      conversation (see _build_thread_text), capturing the final agreed state
      after the full back-and-forth rather than one message's isolated content —
      most customers negotiate orders this way with no PO document at all (see the
      plan this was built from).
    Already-extracted content is skipped without calling Claude — see
    postgres_store.is_known()."""
    thread = gmail_client.get_thread(access_token, thread_id)
    messages = thread.get("messages") or []
    if not messages:
        return []

    attachments_by_message = []
    for m in messages:
        _, attachments = gmail_client.extract_body_and_attachments(m)
        for att in attachments:
            attachments_by_message.append((m, att))

    results = []

    if attachments_by_message:
        for m, att in attachments_by_message:
            if stop_event.is_set():
                break
            pdf_bytes = gmail_client.get_attachment(access_token, m["id"], att["attachment_id"])
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
                result["source_received_at"] = _received_at(m)
                results.append(result)
        return results

    combined_text = _build_thread_text(messages)
    if not combined_text.strip():
        return []

    source_label = f"gmail-thread:{thread_id}"
    file_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()

    if postgres_store.is_known(pg_conn, source_label, file_hash):
        logger.info(f"{source_label}: unchanged since last run — skipping")
        return []

    result = _extract_from_source(
        client, source_label, stop_event, reference_prices, text=combined_text, extraction_method="text",
    )
    if result is not None:
        result["_file_hash"] = file_hash
        result["source_received_at"] = _thread_received_at(messages)
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

        # Refreshed again before each message below rather than held for the whole
        # run — a run over thousands of messages can easily outlast a single access
        # token's ~1hr lifetime (get_valid_access_token() only actually calls
        # Google's refresh endpoint when within 5 minutes of expiry, so calling it
        # repeatedly is cheap/safe, not a real extra round trip most of the time).
        access_token = gmail_client.get_valid_access_token(pg_conn, gmail_client_id, gmail_client_secret)

        since_epoch = None
        if not args.full_backlog and connection.get("last_synced_at"):
            since_epoch = int(connection["last_synced_at"].timestamp())

        sync_started_at = datetime.now(timezone.utc)

        # Resolved once, by ID — NOT via a q=label:"..." string, which was found
        # live to silently return zero results for label names containing an
        # apostrophe or ampersand (see gmail_client.search_messages's docstring).
        all_labels = gmail_client.list_labels(access_token)
        label_id_by_name = {l["name"]: l["id"] for l in all_labels}

        thread_ids, seen = [], set()
        for label in labels:
            label_id = label_id_by_name.get(label)
            if label_id is None:
                print(f"⚠️  Label not found in this Gmail account, skipping: {label!r}")
                continue
            extra_query = f"after:{since_epoch}" if since_epoch is not None else None
            matches = gmail_client.search_messages(access_token, label_id, extra_query, max_results=MAX_SEARCH_RESULTS)
            # Dedupe by thread, not message — multiple matched messages from the
            # same thread collapse into one unit of work (_process_thread fetches
            # the whole thread anyway).
            new_thread_ids = [tid for _, tid in matches if tid not in seen]
            seen.update(new_thread_ids)
            thread_ids.extend(new_thread_ids)
            print(f"🔎 {label}: {len(matches)} message(s) across {len(new_thread_ids)} new thread(s)")

        if args.limit:
            thread_ids = thread_ids[: args.limit]

        print(f"📧 {len(thread_ids)} thread(s) to process across {len(labels)} label(s)")

        if not thread_ids:
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print("Nothing new — cursor updated, exiting.")
            return

        client = anthropic.Anthropic(api_key=anthropic_api_key)
        reference_prices = postgres_store.get_reference_prices(pg_conn)
        stop_event = threading.Event()

        new_results = []
        errors = 0
        skipped = 0
        for thread_id in tqdm(thread_ids, unit="thread", ncols=80):
            if stop_event.is_set():
                break
            try:
                access_token = gmail_client.get_valid_access_token(pg_conn, gmail_client_id, gmail_client_secret)
                results = _process_thread(client, access_token, thread_id, reference_prices, pg_conn, stop_event)
            except Exception as e:
                # Nothing stable to key a Postgres row on here (the failure may have
                # happened before any content — and therefore any file_hash — was
                # ever fetched, e.g. an expired token or a transient network error)
                # — log and skip rather than inventing a hash, so this thread is
                # retried fresh next run instead of the whole publish step failing
                # on a NOT NULL file_hash violation.
                logger.error(f"{thread_id}: unexpected error — {e}")
                skipped += 1
                continue
            for r in results:
                if "error" in r:
                    errors += 1
                new_results.append(r)

        # A skipped thread's messages are necessarily before sync_started_at (it
        # was already found by this run's "after: <old cursor>" search) — advancing
        # the cursor to sync_started_at anyway would permanently drop it from every
        # future incremental search. Only advance when nothing was skipped; a
        # persistently-failing thread just means the same (cheap-to-re-search)
        # window gets rescanned next run too, which is safe, not silent data loss.
        cursor_safe_to_advance = skipped == 0
        if skipped:
            print(f"⚠️  {skipped} thread(s) failed before extraction (see log) — cursor NOT advanced, will retry next run")

        if stop_event.is_set():
            print(f"\n⏸️  Paused: ran out of API credits after {len(new_results)} result(s) this run.")
            print("   Add credits and rerun the same command — already-processed messages are skipped automatically.")
            sys.exit(3)

        if not new_results:
            if cursor_safe_to_advance:
                gmail_client.mark_synced(pg_conn, sync_started_at)
                print("No new extractable content found — cursor updated, exiting.")
            else:
                print("No successful extractions this run — cursor left as-is, exiting.")
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

        if cursor_safe_to_advance:
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print(f"✅ Done — {len(new_results)} new/updated result(s) published.")
        else:
            print(f"✅ Done — {len(new_results)} new/updated result(s) published, but cursor left as-is ({skipped} thread(s) to retry next run).")
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
