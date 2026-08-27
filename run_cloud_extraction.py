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
# (_publish_to_postgres applies the full schema.sql itself at publish time.)

logger = logging.getLogger("run_cloud_extraction")

# A whole email thread rendered to plain text is a far lighter extraction task
# than a scanned multi-page PO PDF — Sonnet handles it well at a fraction of the
# per-call cost, so the cloud pipeline overrides extract_pos.MODEL (which the
# local PDF/vision pipeline still uses) for every thread it sends to the model,
# both the full-thread extraction and the cheap "did these new messages turn this
# into an order?" re-check.
CLOUD_EXTRACTION_MODEL = "claude-sonnet-5"

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


def _ensure_connection(pg_conn, database_url: str):
    """Returns a working Postgres connection — the same one if it's still alive, or
    a fresh one if it's been dropped. A single run can span many minutes of mostly
    Gmail/Claude API calls with the DB connection sitting idle in between; confirmed
    live that a connection held that way can die mid-run ("SSL connection has been
    closed unexpectedly") — most likely Neon's serverless compute autosuspending
    after an idle gap, which no client-side keepalive setting prevents. Called
    before each significant DB touch point rather than once, so a mid-run drop
    costs at most one cheap reconnect, not the whole run."""
    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT 1")
        return pg_conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        try:
            pg_conn.close()
        except Exception:
            pass
        return psycopg2.connect(database_url)


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


def _gmail_thread_url(mailbox_email: str, thread_id: str) -> str:
    """Deep link to the thread in the connected mailbox's web UI. The /u/<email>/
    form pins it to the right account even when the viewer is signed into several
    Google accounts; #all/ opens the thread regardless of which label it lives in."""
    return f"https://mail.google.com/mail/u/{mailbox_email}/#all/{thread_id}"


def _thread_meta(mailbox_email: str, thread_id: str, messages: list) -> dict:
    """Human-facing metadata for a thread — subject, who sent it, first/last
    timestamps, message count, attachment filenames, and a link. Persisted to
    gmail_thread_meta (see schema.sql) so an extraction result — especially an
    errored, low-information one like "not a purchase order" — can be traced back
    to the actual email. messages must be chronological (get_thread() returns them
    that way)."""
    senders, customer_senders, attachment_names = [], [], []
    for m in messages:
        frm = (gmail_client.message_headers(m).get("from") or "").strip()
        if frm and frm not in senders:
            senders.append(frm)
            if GARFIELD_DOMAIN not in frm.lower():
                customer_senders.append(frm)
        for att in gmail_client.extract_body_and_attachments(m)[1]:
            name = att.get("filename")
            if name and name not in attachment_names:
                attachment_names.append(name)

    timestamps = sorted(t for t in (_received_at(m) for m in messages) if t)
    subject = (gmail_client.message_headers(messages[0]).get("subject") or "").strip()

    return {
        "subject": subject or None,
        # Customer-side sender(s) are what you actually want to see on a bad
        # extraction; fall back to every sender if the thread is somehow all ours.
        "from_addrs": ", ".join(customer_senders or senders) or None,
        "first_message_at": timestamps[0] if timestamps else None,
        "last_message_at": timestamps[-1] if timestamps else None,
        "message_count": len(messages),
        "attachment_names": ", ".join(attachment_names) or None,
        "url": _gmail_thread_url(mailbox_email, thread_id),
    }


def _looks_like_new_order(client: anthropic.Anthropic, source_label: str, new_text: str) -> bool:
    """Cheap yes/no gate used only for a thread already classified NOT a purchase
    order that has since gained messages: do the NEW messages alone contain a
    customer placing or confirming a concrete order (specific products AND
    quantities)? Deliberately biased toward True — a False here skips the full
    whole-thread re-extraction, so a wrong False means a missed PO, while a wrong
    True just costs the one full extraction we'd have done unconditionally before.
    One tiny call (max_tokens=5, a few hundred input tokens) in place of resending
    the whole thread to the model every time it gets a reply."""
    try:
        resp = client.messages.create(
            model=CLOUD_EXTRACTION_MODEL,
            max_tokens=5,
            system="You answer with exactly one word: YES or NO.",
            messages=[{
                "role": "user",
                "content": (
                    "The earlier part of an email thread was already determined NOT to be a "
                    "purchase order. Below are ONLY the new messages added to it since then.\n\n"
                    f"{new_text[:4000]}\n\n"
                    "Do these new messages contain a customer placing or confirming a concrete "
                    "order — specific product(s) AND quantities? Answer YES or NO. If you are "
                    "unsure, answer YES."
                ),
            }],
        )
    except anthropic.APIError as e:
        # Don't let the cheap gate swallow a thread — fall back to a full extraction.
        logger.warning(f"{source_label}: new-message gate call failed ({e}) — doing full re-extraction")
        return True
    answer = "".join(b.text for b in resp.content if b.type == "text").strip().upper()
    return not answer.startswith("NO")


def _process_thread(
    client: anthropic.Anthropic,
    access_token: str,
    thread_id: str,
    reference_prices: dict,
    pg_conn,
    stop_event: threading.Event,
    mailbox_email: str,
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

    # Written every run the thread is seen, before any skip/extraction decision, so
    # the dashboard can always trace a result back to the email. link_thread_rows
    # also stamps gmail_thread_id onto any already-stored row this thread produced
    # (the "gmail-thread:<id>" text row and each attachment filename) that predates
    # this column — so a one-off --full-backlog run backfills every old row.
    postgres_store.upsert_gmail_thread_meta(
        pg_conn, thread_id, **_thread_meta(mailbox_email, thread_id, messages)
    )
    postgres_store.link_thread_rows(
        pg_conn, thread_id,
        [f"gmail-thread:{thread_id}"] + [att["filename"] for _, att in attachments_by_message if att.get("filename")],
    )

    results = []

    if attachments_by_message:
        seen_in_thread = set()  # (source_label, file_hash) — a reply that quotes/
        # re-includes an earlier message's attachment (or a customer literally
        # resending the same file) means the identical PDF can appear on more than
        # one message in one thread; without this, both would get extracted
        # independently and produce two identical (source_file, file_hash) rows,
        # which crash the batch publish (Postgres: "ON CONFLICT DO UPDATE command
        # cannot affect row a second time") — confirmed live in a real run.
        for m, att in attachments_by_message:
            if stop_event.is_set():
                break
            pdf_bytes = gmail_client.get_attachment(access_token, m["id"], att["attachment_id"])
            file_hash = hashlib.sha256(pdf_bytes).hexdigest()
            source_label = att["filename"]

            if (source_label, file_hash) in seen_in_thread:
                continue
            seen_in_thread.add((source_label, file_hash))

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
                result["gmail_thread_id"] = thread_id
                results.append(result)
        return results

    combined_text = _build_thread_text(messages)
    if not combined_text.strip():
        return []

    source_label = f"gmail-thread:{thread_id}"
    file_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
    message_count = len(messages)

    state = postgres_store.get_thread_state(pg_conn, thread_id)
    if postgres_store.is_known(pg_conn, source_label, file_hash) or (
        state is not None and state["last_file_hash"] == file_hash
    ):
        logger.info(f"{source_label}: unchanged since last run — skipping")
        return []

    # Cheap path for a thread already fully processed as NOT a purchase order that
    # has since only grown: re-check just the new messages instead of resending the
    # whole thread to the model. (The unchanged case is handled above; a thread
    # that shrank or whose earlier text was edited has message_count <= the stored
    # count and falls through to a full re-extraction.)
    if state is not None and not state["was_po"] and message_count > state["message_count"]:
        new_text = _build_thread_text(messages[state["message_count"]:])
        if new_text.strip() and not _looks_like_new_order(client, source_label, new_text):
            logger.info(
                f"{source_label}: {message_count - state['message_count']} new message(s), "
                "still not an order — skipping full re-extraction"
            )
            postgres_store.upsert_thread_state(pg_conn, thread_id, message_count, file_hash, was_po=False)
            return []

    result = _extract_from_source(
        client, source_label, stop_event, reference_prices,
        text=combined_text, extraction_method="text", model=CLOUD_EXTRACTION_MODEL,
    )
    if result is not None:
        result["_file_hash"] = file_hash
        result["source_received_at"] = _thread_received_at(messages)
        result["gmail_thread_id"] = thread_id
        results.append(result)
        # Record thread state only for a *settled* disposition — a clean extraction
        # or a "not a purchase order" classification. A real failure (credit/API
        # error, timeout) must NOT be recorded, or the state's last_file_hash would
        # make this thread skip its own retry next run even though is_known() now
        # allows it.
        settled = "error" not in result or result["error"] == postgres_store.NOT_A_PO_ERROR
        if settled:
            postgres_store.upsert_thread_state(
                pg_conn, thread_id, message_count, file_hash, was_po=("error" not in result),
            )

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
        # The thread loop reads gmail_thread_state / writes gmail_thread_meta before
        # the publish step (which applies the full schema.sql) runs — ensure just
        # those exist up front. Cheaper than a whole-schema apply against a cold DB.
        postgres_store.ensure_cloud_schema(pg_conn)

        connection = gmail_client.get_connection(pg_conn)
        if connection is None:
            print("❌ Not connected to Gmail — connect via the dashboard's ✉️ Email Ingestion page first.", file=sys.stderr)
            sys.exit(1)
        mailbox_email = connection["email_address"]  # for thread deep links (see _thread_meta)

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
            # the whole thread anyway). Must update `seen` as we go: a single
            # label's own match list already contains one entry per labeled
            # message, so an N-message thread appears N times in `matches` — a
            # comprehension that only checks the pre-loop `seen` would let every
            # one of those copies through and extract the same thread N times.
            new_thread_ids = []
            for _, tid in matches:
                if tid in seen:
                    continue
                seen.add(tid)
                new_thread_ids.append(tid)
            thread_ids.extend(new_thread_ids)
            print(f"🔎 {label}: {len(matches)} message(s) across {len(new_thread_ids)} new thread(s)")

        if args.limit:
            thread_ids = thread_ids[: args.limit]

        print(f"📧 {len(thread_ids)} thread(s) to process across {len(labels)} label(s)")
        print(f"🤖 Text-thread extraction model: {CLOUD_EXTRACTION_MODEL}")

        if not thread_ids:
            pg_conn = _ensure_connection(pg_conn, database_url)
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
                pg_conn = _ensure_connection(pg_conn, database_url)
                access_token = gmail_client.get_valid_access_token(pg_conn, gmail_client_id, gmail_client_secret)
                results = _process_thread(
                    client, access_token, thread_id, reference_prices, pg_conn, stop_event, mailbox_email
                )
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

        # Defensive: dedupe by (source_file, file_hash) across the whole run, not
        # just within one thread's own attachment loop — the identical attachment
        # could in principle appear on two separate threads (e.g. a customer
        # resending the same file in a new conversation). Two rows sharing a
        # (source_file, file_hash) crash the batch publish's single ON CONFLICT
        # statement (confirmed live), and since a hash match means identical
        # content, dropping the extra copy loses nothing.
        deduped, seen_keys = [], set()
        for r in new_results:
            key = (r.get("_source_file"), r.get("_file_hash"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(r)
        if len(deduped) < len(new_results):
            print(f"ℹ️  Dropped {len(new_results) - len(deduped)} duplicate (source_file, file_hash) result(s) this run")
        new_results = deduped
        errors = sum(1 for r in new_results if "error" in r)  # recomputed post-dedup —
        # the running count above included the dropped duplicate(s) too

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
                pg_conn = _ensure_connection(pg_conn, database_url)
                gmail_client.mark_synced(pg_conn, sync_started_at)
                print("No new extractable content found — cursor updated, exiting.")
            else:
                print("No successful extractions this run — cursor left as-is, exiting.")
            return

        print(f"📈 {len(new_results) - errors} extracted successfully, {errors} error(s)")

        print("🔄 Re-annotating revisions across the full dataset...")
        pg_conn = _ensure_connection(pg_conn, database_url)
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
            pg_conn = _ensure_connection(pg_conn, database_url)
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print(f"✅ Done — {len(new_results)} new/updated result(s) published.")
        else:
            print(f"✅ Done — {len(new_results)} new/updated result(s) published, but cursor left as-is ({skipped} thread(s) to retry next run).")
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
