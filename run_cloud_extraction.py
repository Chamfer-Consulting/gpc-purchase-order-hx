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
import copy
import hashlib
import logging
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import anthropic
import psycopg2
from tqdm import tqdm

import extraction_reviews
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

# Tiny YES/NO gate calls (does this thread actually contain an order?) use the
# cheapest model — the task is trivial classification, not extraction, and a full
# thread otherwise costs a Sonnet extraction just to come back "not a purchase
# order" (~40% of threads under a general customer label do exactly that).
GATE_MODEL = "claude-haiku-4-5-20251001"

# Publish accumulated results this often (threads processed, not results), so a
# job timeout / kill / out-of-credits pause mid-run doesn't discard paid
# extraction work — a --full-backlog run over thousands of threads can easily
# outlast a CI job's time limit, and everything since the last publish would be
# lost and re-extracted (re-paid for) next run. Each flush re-reads the whole
# dataset and re-runs annotate_revisions over it, so this is a balance: smaller =
# less re-extraction risk on a kill, larger = less repeated full-dataset churn.
CHECKPOINT_EVERY = 150

# _flush()'s publish step (full-dataset read + annotate + batched upsert) can hit a
# transient DB error mid-run — most often Neon's serverless compute having
# autosuspended after the idle gap since the previous checkpoint ("SSL connection
# has been closed unexpectedly"). Retry with exponential backoff (5, 10, 20, 40s)
# before giving up, so a slow Neon cold-start is ridden out rather than aborting a
# multi-hour backlog and stranding ~CHECKPOINT_EVERY threads of paid work.
FLUSH_MAX_ATTEMPTS = 5
FLUSH_RETRY_BASE_SLEEP_SECONDS = 5

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

# PDF attachments on customer threads are mostly NOT purchase orders — compliance
# and reference docs (food-safety certs, USDA audits, insurance COIs, W-9s, safety
# data sheets, spec/price sheets, packing lists, BOLs). Each one otherwise costs a
# full paid Claude extraction call just to come back is_po: false. This filename
# check skips the unambiguous ones before any API call. Kept deliberately tight —
# only terms that are never a PO — so a genuinely oddly-named PO isn't dropped;
# anything not matched still goes to the model as before. The text-thread path is
# unaffected (a customer who types an order into the email body still extracts).
_NON_PO_FILENAME_PATTERN = re.compile(
    r"""
      certificat | \bcert\b | \bcoi\b            # certificates of X / insurance
    | audit | \bgap\b | \bgfsi\b | \bsqf\b | haccp | \bfsma\b   # food-safety audits
    | usda | \busda\b
    | insurance | liabilit
    | \bw-?9\b | \bw-?8\b | \b1099\b | \bach\b | credit\s*app | remittance
    | \bsds\b | \bmsds\b | safety\s*data
    | spec\s*sheet | specification | data\s*sheet
    | price\s*list | pricelist | \bcatalog
    | packing\s*(list|slip) | (?<![a-z])bol(?![a-z]) | bill\s*of\s*lading
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A purchase order — even one PDF bundling an original plus a revision, even with a
# page of boilerplate terms — is a short document. A PDF whose extracted text runs
# to tens of thousands of characters is a report / contract / cert packet, not an
# order, so skip it before the (paid) model call rather than truncating it to
# MAX_TEXT_CHARS and asking anyway. Set well above MAX_TEXT_CHARS (15k) so the
# 15k-25k band still extracts-with-truncation as before; only the clearly-not-a-PO
# range is dropped. Only bounds the text-extractable path — a scanned PO with no
# extractable text still goes to vision regardless of page count.
NON_PO_TEXT_CEILING = 30000

# QuickBooks / Intuit send an "Invoice <n> from Garfield Produce Company" email
# (plus payment receipts, statements, reminders) from an intuit.com / quickbooks.com
# address. That is a copy of a QBO invoice we already hold on the invoice side —
# never a customer purchase order. If every non-Garfield sender in the thread is
# one of these addresses, skip the thread entirely before any model call. A thread
# where a real person ALSO wrote (e.g. a customer forwarding the invoice with a
# question) is not matched — it still goes to extraction as before.
_INTUIT_SENDER = re.compile(r"@[\w.-]*\b(?:intuit|quickbooks)\.com\b", re.IGNORECASE)


def _is_invoice_notification(messages: list) -> bool:
    non_ours = [
        frm.lower()
        for frm in ((gmail_client.message_headers(m).get("from") or "") for m in messages)
        if frm and GARFIELD_DOMAIN not in frm.lower()
    ]
    return bool(non_ours) and all(_INTUIT_SENDER.search(f) for f in non_ours)


def configure_logging(log_path: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )


def _connect(database_url: str):
    """psycopg2.connect with a bounded connect timeout and TCP keepalives. Keepalives
    don't stop Neon's serverless compute from autosuspending an idle connection, but
    they make the kernel notice the dead peer in ~30-60s — without them a query (or
    even a `SELECT 1` probe) on a silently-dropped socket blocks on the OS TCP
    timeout, which is minutes. Observed live: a ~5-minute stall before a checkpoint
    flush finally raised "SSL connection has been closed unexpectedly".

    autocommit is on: the thread-loop connection does a read (is_known / a token
    check) and then spends seconds-to-minutes on Gmail + Claude calls before its
    next DB touch. Under psycopg2's default (autocommit off) that first read opens
    a transaction that then sits "idle in transaction" holding an AccessShareLock
    on purchase_orders for the whole gap. The checkpoint flush re-applies the full
    schema.sql (CREATE TABLE IF NOT EXISTS ...), which needs a briefly-conflicting
    lock on the same table — against a Supabase pooler that blocks until the
    database's 2-minute statement_timeout kills it ("canceling statement due to
    statement timeout"), failing every checkpoint. Every write in the thread loop
    is an idempotent upsert, so committing each immediately is also strictly better
    for crash-resumability."""
    conn = psycopg2.connect(
        database_url,
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
        # Bounds how long the socket may wait on unacknowledged data mid-query
        # before erroring — keepalives only cover an *idle* socket, this covers an
        # active one. Without it a mid-query drop blocks on the OS default (~5 min,
        # observed live) instead of failing fast enough for a retry to matter.
        tcp_user_timeout=45000,
    )
    conn.autocommit = True
    return conn


def _ensure_connection(pg_conn, database_url: str):
    """Returns a working Postgres connection — the same one if it's still alive, or
    a fresh one if it's been dropped. A single run can span many minutes of mostly
    Gmail/Claude API calls with the DB connection sitting idle in between; confirmed
    live that a connection held that way can die mid-run ("SSL connection has been
    closed unexpectedly") — most likely Neon's serverless compute autosuspending
    after an idle gap. Called before each significant DB touch point rather than
    once, so a mid-run drop costs at most one cheap reconnect, not the whole run."""
    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT 1")
        return pg_conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        try:
            pg_conn.close()
        except Exception:
            pass
        return _connect(database_url)


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
    """Deep link to the thread in the connected mailbox's web UI. `authuser=<email>`
    pins it to the right account across multi-account sign-in — the older
    /mail/u/<email>/ path form makes Gmail throw error #6446 when the browser can't
    map the address to a signed-in session slot. #all/ opens the thread whatever
    label it lives under."""
    return f"https://mail.google.com/mail/?authuser={mailbox_email}#all/{thread_id}"


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


def _is_customer_message(message: dict) -> bool:
    """True if this message was sent by someone other than Garfield Produce — i.e.
    the customer side of the thread. A thread with no customer message at all is our
    own outbound / an internal forward, never a customer PO."""
    frm = (gmail_client.message_headers(message).get("from") or "").lower()
    return GARFIELD_DOMAIN not in frm


def _yes_no_gate(
    client: anthropic.Anthropic, source_label: str, question: str, body: str, examples: str = ""
) -> bool:
    """One tiny YES/NO classification call, biased to YES. Returns True on YES or on
    any API error — a wrong True just costs the full extraction we'd have done
    anyway, a wrong False would drop a real PO. `examples`, if given, is a few-shot
    block from human review decisions, inserted ahead of the content."""
    preamble = f"{examples}\n\n---\n\n" if examples else ""
    try:
        resp = client.messages.create(
            model=GATE_MODEL,
            max_tokens=5,
            system="You answer with exactly one word: YES or NO.",
            messages=[{"role": "user", "content": f"{question}\n\n{preamble}{body}\n\nAnswer YES or NO. If unsure, answer YES."}],
        )
    except anthropic.APIError as e:
        logger.warning(f"{source_label}: YES/NO gate call failed ({e}) — proceeding with full extraction")
        return True
    answer = "".join(b.text for b in resp.content if b.type == "text").strip().upper()
    return not answer.startswith("NO")


def _looks_like_new_order(client: anthropic.Anthropic, source_label: str, new_text: str) -> bool:
    """Gate for a thread already classified NOT a purchase order that has since
    gained messages: do the NEW messages alone contain a customer placing or
    confirming a concrete order? Saves resending the whole thread on every reply."""
    return _yes_no_gate(
        client, source_label,
        "The earlier part of an email thread was already determined NOT to be a purchase "
        "order. Below are ONLY the new messages added to it since then. Do these new "
        "messages contain a customer placing or confirming a concrete order — specific "
        "product(s) AND quantities?",
        new_text[:4000],
    )


def _thread_looks_like_order(
    client: anthropic.Anthropic, source_label: str, thread_text: str, examples: str = ""
) -> bool:
    """Pre-extraction gate for a brand-new thread: does the conversation anywhere
    contain a customer placing or confirming a concrete produce order (specific
    product(s) AND quantities)? A cheap Haiku call in front of the Sonnet
    extraction, which for a general customer label comes back 'not a purchase
    order' ~40% of the time."""
    return _yes_no_gate(
        client, source_label,
        "Below is a full email thread between Garfield Produce and a customer, each message "
        "labelled by sender. Does this thread contain the CUSTOMER placing or confirming a "
        "concrete order — specific produce product(s) AND quantities? Pricing questions, "
        "availability chatter, logistics, invoices, and relationship email are NOT orders.",
        thread_text[:6000],
        examples=examples,
    )


# ── Text modifications to an existing PO ──────────────────────────────────────
#
# A customer can change an order they've already placed (by PDF or by earlier
# email) without sending a revised PDF — a plain message in the same thread, or a
# whole new email. We never store the change as a delta: on detecting one, we
# re-extract the COMPLETE resulting order by handing the model the order's current
# structured state plus the change messages. It then lands as an ordinary full
# revision row (distinct _source_file so it can't collide with the PDF/thread row),
# grouped under the same PO by annotate_revisions via _group_override.

MODIFICATION_INSTRUCTION = (
    "The block below headed CURRENT PURCHASE ORDER is an order the customer has "
    "ALREADY placed. The messages after it, headed LATER CUSTOMER MESSAGES, are "
    "newer messages from that customer. Apply every change they request "
    "(quantities, products, sizes, delivery date) to the current order and output "
    "the COMPLETE resulting purchase order via the extract_po tool — every line, "
    "not only the changed ones, with the changes applied. Keep every line they did "
    "not mention exactly as it is. If the later messages request no change to order "
    "content, output the current order unchanged. If the later messages are not "
    "about this order at all, set is_po to false."
)

MODIFICATION_SOURCE_SUFFIX = "#mod"  # appended to gmail-thread:<id> for a text-mod row

# Words that, in a thread with no PDF, suggest the customer is changing an order
# placed elsewhere rather than placing a fresh one.
_MODIFICATION_HINT = re.compile(
    r"\b(revis|amend|update the (order|po)|change (the )?(order|po|qty|quantity)|"
    r"instead of|scratch that|correction|add to (the |my |our )?(order|po)|"
    r"remove from|cancel the|make it|bump (it|the))\b",
    re.IGNORECASE,
)

# A subject line explicitly marking the email as a revised order — a strong,
# high-precision revision signal on its own (see _resolve_revision_target).
_SUBJECT_REVISED = re.compile(
    r"\b(revis(ed|ion)?|amend(ed|ment)?|corrected|re-?issued?|\brev\.?\b|\b[rv]\s?\d\b)\b",
    re.IGNORECASE,
)
# PO number in a subject: "PO 583741", "P.O.# 00583741", "#583741", or a bare
# 5-12 digit run (only trusted because we already know the subject says "revised").
_SUBJECT_PO_NUM = re.compile(
    r"(?:\bp\.?\s*o\.?\s*(?:number|no|#)?\s*[:#-]?\s*|#)\s*(\d{4,12})|\b(\d{5,12})\b",
    re.IGNORECASE,
)


def _norm_num(value) -> str:
    """Digits only, leading zeros stripped — matches qbo_matcher.normalize_po_number
    without importing it into the pipeline."""
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def _subject_po_numbers(subject: str) -> list[str]:
    out = []
    for m in _SUBJECT_PO_NUM.finditer(subject or ""):
        n = m.group(1) or m.group(2)
        if n and n not in out:
            out.append(n)
    return out


def _resolve_revision_target(pg_conn, result: dict, subject: str, source_label: str) -> dict | None:
    """The order this thread revises, or None. Two signals:
      1. the extracted po_number matches an existing clean PO (the original
         Case-B check), OR
      2. the SUBJECT line says "revised" AND a PO number (from the subject, or
         the body) resolves to an existing clean PO.
    Match is tried exact first, then digits-only / leading-zeros-stripped."""
    def _lookup(num: str) -> dict | None:
        if not num:
            return None
        return (postgres_store.clean_po_by_number(pg_conn, num, exclude_source_file=source_label)
                or postgres_store.find_po_by_normalized_number(pg_conn, _norm_num(num),
                                                               exclude_source_file=source_label))

    body_num = (result.get("po_number") or "").strip()
    hit = _lookup(body_num)
    if hit is not None:
        return hit

    if _SUBJECT_REVISED.search(subject or ""):
        for num in ([body_num] if body_num else []) + _subject_po_numbers(subject):
            hit = _lookup(num)
            if hit is not None:
                logger.info(
                    f"{source_label}: subject marks a revision of PO {num} — auto-grouped"
                )
                return hit
    return None


def _render_prior_order(prior: dict) -> str:
    """A stored PO result dict rendered as compact readable text, to seed a
    modification re-extraction."""
    lines = [
        f"CURRENT PURCHASE ORDER"
        f"  (PO {prior.get('po_number') or '—'}, customer {prior.get('customer_name') or '—'}"
        f", PO date {prior.get('po_date') or '—'}, delivery {prior.get('delivery_date') or '—'})"
    ]
    for it in prior.get("line_items") or []:
        if it.get("is_removed"):
            continue
        name = it.get("product_name") or it.get("product_raw") or "?"
        size = f" {it['container_size']}" if it.get("container_size") else ""
        price = f" @ {it['unit_price']}" if it.get("unit_price") is not None else ""
        lines.append(f"  - {it.get('quantity') or '?'} x {name}{size}{price}")
    if prior.get("subtotal") is not None or prior.get("total") is not None:
        lines.append(f"  (subtotal {prior.get('subtotal')}, tax {prior.get('tax')}, total {prior.get('total')})")
    return "\n".join(lines)


def _thread_modifies_order(client, source_label, mod_text, prior_summary, examples="") -> bool:
    return _yes_no_gate(
        client, source_label,
        "A customer has already placed the order below (CURRENT ORDER). After it are later "
        "messages from that same customer (LATER MESSAGES). Do the later messages ask to "
        "CHANGE that order — different quantities, products, sizes, or delivery date?",
        f"CURRENT ORDER:\n{prior_summary[:2500]}\n\nLATER MESSAGES:\n{mod_text[:3500]}",
        examples=examples,
    )


def _line_multiset(items) -> dict:
    """{(product, size): total_qty} — for comparing two orders' content."""
    out = {}
    for it in items or []:
        if it.get("is_removed"):
            continue
        k = (it.get("product_name") or it.get("product_raw") or "?", it.get("container_size") or "")
        try:
            out[k] = out.get(k, 0) + float(it.get("quantity") or 0)
        except (TypeError, ValueError):
            out[k] = out.get(k, 0)
    return out


def _orders_equivalent(a_items, b_items) -> bool:
    return _line_multiset(a_items) == _line_multiset(b_items)


def _extract_modification(client, source_label, prior, mod_text, fewshot_block, stop_event) -> dict | None:
    """Seeded re-extraction: prior order state + the change messages -> the complete
    revised order. Returns the result dict, or None if the model says it's not a
    change / not about this order, or if the result is content-equivalent to prior
    (no real modification -> no spurious revision row)."""
    prior_block = _render_prior_order(prior)
    payload = (
        f"{MODIFICATION_INSTRUCTION}\n\n{prior_block}\n\n"
        f"=== LATER CUSTOMER MESSAGES ===\n{mod_text}"
    )
    result = _extract_from_source(
        client, source_label, stop_event, None,
        text=payload, extraction_method="text-mod", model=CLOUD_EXTRACTION_MODEL,
        extra_guidance=fewshot_block,
    )
    if result is None or "error" in result:
        return result if (result and "error" in result) else None
    if _orders_equivalent(result.get("line_items"), prior.get("line_items")):
        logger.info(f"{source_label}: modification re-extraction matches the current order — no revision written")
        return None
    # Carry forward identity fields the mod text may not restate.
    for k in ("po_number", "customer_name", "customer_id", "delivery_date"):
        if not result.get(k) and prior.get(k):
            result[k] = prior[k]
    return result


def _thread_modification(
    client, thread_id, messages, attachments_by_message, pg_conn, fewshot_block, stop_event, extracted_keys
) -> dict | None:
    """Case A — a thread that carries a PDF PO and also has customer messages AFTER
    the latest PDF that change the order. Returns a full revised-order result keyed
    'gmail-thread:<id>#mod', grouped under the PDF's PO, or None."""
    pdf_times = [t for t in (_received_at(m) for m, _ in attachments_by_message) if t]
    if not pdf_times:
        return None
    latest_pdf_ts = max(pdf_times)

    later_msgs = [
        m for m in messages
        if _is_customer_message(m) and (_received_at(m) or "") > latest_pdf_ts
    ]
    if not later_msgs:
        return None

    mod_text = _build_thread_text(later_msgs)
    if not mod_text.strip():
        return None

    mod_source = f"gmail-thread:{thread_id}{MODIFICATION_SOURCE_SUFFIX}"
    mod_hash = hashlib.sha256(mod_text.encode("utf-8")).hexdigest()
    if (mod_source, mod_hash) in extracted_keys or postgres_store.is_known(pg_conn, mod_source, mod_hash):
        return None

    prior = postgres_store.latest_thread_po(pg_conn, thread_id)
    if prior is None:
        return None  # nothing stored to modify (the PDF itself may have failed)

    if not _thread_modifies_order(
        client, mod_source, mod_text, _render_prior_order(prior), examples=fewshot_block
    ):
        return None

    result = _extract_modification(client, mod_source, prior, mod_text, fewshot_block, stop_event)
    if result is None:
        return None

    result["_file_hash"] = mod_hash
    result["_source_file"] = mod_source
    result["source_received_at"] = max(t for t in (_received_at(m) for m in later_msgs) if t)
    result["gmail_thread_id"] = thread_id
    result["_group_override"] = prior.get("po_number") or prior.get("_source_file")
    extracted_keys.add((mod_source, mod_hash))
    logger.info(
        f"{mod_source}: text modification to PO {prior.get('po_number')} — revised order re-extracted"
    )
    return result


def _process_thread(
    client: anthropic.Anthropic,
    access_token: str,
    thread_id: str,
    reference_prices: dict,
    pg_conn,
    stop_event: threading.Event,
    mailbox_email: str,
    extracted_keys: set,
    fewshot_block: str = "",
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
    postgres_store.is_known() for content already in Postgres, plus `extracted_keys`
    (a run-scoped set of (source_file, file_hash) already handled this run) for
    content extracted-but-not-yet-published, e.g. the same attachment riding on two
    different threads within one checkpoint window."""
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

    # A thread with no customer-side message is our own outbound or an internal
    # forward — it can't be a customer PO. Skip before any Gmail attachment fetch
    # or model call. (Meta is already written above, so it's still traceable.)
    if not any(_is_customer_message(m) for m in messages):
        logger.info(f"gmail-thread:{thread_id}: no customer-side message in thread — skipping (no API call)")
        return []

    # A QuickBooks/Intuit invoice-notification email — a copy of a QBO invoice,
    # never a PO. Skip before any model call (meta already written above).
    if _is_invoice_notification(messages):
        logger.info(
            f"gmail-thread:{thread_id}: QuickBooks/Intuit invoice notification — skipping (no API call)"
        )
        return []

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
            pdf_bytes = gmail_client.attachment_bytes(access_token, m["id"], att)
            file_hash = hashlib.sha256(pdf_bytes).hexdigest()
            source_label = att["filename"]

            if (source_label, file_hash) in seen_in_thread:
                continue
            seen_in_thread.add((source_label, file_hash))

            if postgres_store.is_known(pg_conn, source_label, file_hash):
                logger.info(f"{source_label}: unchanged since last run — skipping")
                continue
            if (source_label, file_hash) in extracted_keys:
                logger.info(f"{source_label}: already extracted earlier this run — skipping")
                continue
            if _NON_PO_FILENAME_PATTERN.search(source_label):
                logger.info(f"{source_label}: filename is a non-PO document type — skipping (no API call)")
                continue

            decision = extraction_reviews.get_decision(pg_conn, "file", source_label)
            if (
                decision
                and not extraction_reviews.is_stale(decision, file_hash)
                and extraction_reviews.has_authoritative_result(decision)
            ):
                result = extraction_reviews.synthesized_result(decision, source_label, "review")
                result["_file_hash"] = file_hash
                result["source_received_at"] = _received_at(m)
                result["gmail_thread_id"] = thread_id
                results.append(result)
                extracted_keys.add((source_label, file_hash))
                logger.info(f"{source_label}: applied human review decision ({decision['verdict']}) — no model call")
                continue

            text = extract_pdf_text(pdf_bytes)
            if text and len(text) > NON_PO_TEXT_CEILING:
                logger.info(
                    f"{source_label}: {len(text)} chars of text — far larger than any purchase order, "
                    "treating as a non-PO document — skipping (no API call)"
                )
                continue
            if text:
                postgres_store.upsert_snapshot(pg_conn, "file", source_label, text, file_hash)
            pdf_b64 = None if text else pdf_to_base64(pdf_bytes)
            result = _extract_from_source(
                client, source_label, stop_event, reference_prices,
                text=text, pdf_b64=pdf_b64, extraction_method="text" if text else "vision",
                extra_guidance=fewshot_block,
            )
            if result is not None:
                result["_file_hash"] = file_hash
                result["source_received_at"] = _received_at(m)
                result["gmail_thread_id"] = thread_id
                results.append(result)
                extracted_keys.add((source_label, file_hash))

        # The customer may have changed the order in a later message without sending
        # a revised PDF — pick that up as a full revised-order revision. Runs even
        # when every PDF was is_known (an incremental run over a thread that just
        # gained a change message).
        if not stop_event.is_set():
            mod_result = _thread_modification(
                client, thread_id, messages, attachments_by_message,
                pg_conn, fewshot_block, stop_event, extracted_keys,
            )
            if mod_result is not None:
                results.append(mod_result)

        if results:
            return results
        # Every attachment was skipped or filtered out as a non-PO document. If the
        # thread already has a clean PO row (extracted from an attachment on an
        # earlier run), stop — re-reading the body would just duplicate it.
        # Otherwise the order may be in the email body itself, so fall through to
        # whole-thread text extraction rather than returning nothing.
        if postgres_store.thread_has_clean_po(pg_conn, thread_id):
            return []
        logger.info(
            f"gmail-thread:{thread_id}: all {len(attachments_by_message)} attachment(s) "
            "skipped/filtered — falling back to thread-text extraction"
        )

    combined_text = _build_thread_text(messages)
    if not combined_text.strip():
        return []

    source_label = f"gmail-thread:{thread_id}"
    file_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
    message_count = len(messages)
    subject = (gmail_client.message_headers(messages[0]).get("subject") or "").strip()

    # Keep the review queue / eval able to see what the model saw.
    postgres_store.upsert_snapshot(pg_conn, "thread", thread_id, combined_text, file_hash)

    # A human review decision on this thread is authoritative — re-asserted every
    # run so it survives a re-extraction. Checked before the is_known short-circuit
    # so a 'not_po' verdict also overrides a stale clean PO row from before the
    # decision. A decision made on different content (is_stale) reverts to advisory.
    decision = extraction_reviews.get_decision(pg_conn, "thread", thread_id)
    if (
        decision
        and not extraction_reviews.is_stale(decision, file_hash)
        and extraction_reviews.has_authoritative_result(decision)
    ):
        result = extraction_reviews.synthesized_result(decision, source_label, "review")
        result["_file_hash"] = file_hash
        result["source_received_at"] = _thread_received_at(messages)
        result["gmail_thread_id"] = thread_id
        results.append(result)
        extracted_keys.add((source_label, file_hash))
        if result.get("error") == postgres_store.NOT_A_PO_ERROR:
            postgres_store.upsert_thread_state(pg_conn, thread_id, message_count, file_hash, was_po=False)
        else:
            result["_thread_state"] = (thread_id, message_count, file_hash, True)
        logger.info(f"{source_label}: applied human review decision ({decision['verdict']}) — no model call")
        return results

    # A reviewer said "this thread is a revision of PO X" without giving the lines —
    # re-extract the thread as a modification seeded with PO X's current state and
    # group it there.
    if (
        decision
        and not extraction_reviews.is_stale(decision, file_hash)
        and extraction_reviews.wants_modification_extract(decision)
    ):
        prior = (postgres_store.clean_po_by_number(pg_conn, decision["revision_of"])
                 or postgres_store.latest_thread_po(pg_conn, thread_id))
        if prior is not None:
            mres = _extract_modification(client, source_label, prior, combined_text, fewshot_block, stop_event)
            if mres is not None and "error" not in mres:
                mres["_file_hash"] = file_hash
                mres["_source_file"] = source_label
                mres["source_received_at"] = _thread_received_at(messages)
                mres["gmail_thread_id"] = thread_id
                mres["_group_override"] = decision["revision_of"]
                mres["_thread_state"] = (thread_id, message_count, file_hash, True)
                results.append(mres)
                extracted_keys.add((source_label, file_hash))
                logger.info(f"{source_label}: reviewer-directed revision of {decision['revision_of']} — revised order extracted")
                return results
        logger.warning(f"{source_label}: reviewer marked it a revision of {decision['revision_of']} but that PO wasn't found — extracting normally")

    state = postgres_store.get_thread_state(pg_conn, thread_id)
    # The last_file_hash short-circuit is only trusted for a thread recorded as NOT an
    # order (was_po=False) — there the state row IS the whole record and nothing can be
    # lost by skipping. For was_po=True the authoritative signal is is_known() (a
    # published purchase_orders row); an unchanged hash with no published PO means a
    # prior run extracted it but died before publishing, so it must be re-processed.
    if (
        postgres_store.is_known(pg_conn, source_label, file_hash)
        or (source_label, file_hash) in extracted_keys
        or (state is not None and not state["was_po"] and state["last_file_hash"] == file_hash)
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

    # Brand-new thread (no prior state): a cheap Haiku YES/NO in front of the full
    # Sonnet extraction. ~40% of threads under a general customer label are not
    # orders at all — this skips the expensive call on those. Biased to YES, so an
    # ambiguous thread still gets the full extraction. Threads with prior state are
    # already covered: unchanged ones short-circuited above, grown not-a-PO ones by
    # the new-messages gate, and prior POs must re-extract fully on any change.
    if state is None and not _thread_looks_like_order(client, source_label, combined_text, examples=fewshot_block):
        logger.info(f"{source_label}: pre-extraction gate — no concrete customer order — skipping full extraction")
        postgres_store.upsert_thread_state(pg_conn, thread_id, message_count, file_hash, was_po=False)
        return []

    result = _extract_from_source(
        client, source_label, stop_event, reference_prices,
        text=combined_text, extraction_method="text", model=CLOUD_EXTRACTION_MODEL,
        extra_guidance=fewshot_block,
    )
    if result is not None and "error" not in result:
        # Case B: this text thread is a modification of an order captured elsewhere
        # (a PDF, another thread) — because its extracted po_number matches one, OR
        # its subject line explicitly says "revised" and names a resolvable PO.
        other = _resolve_revision_target(pg_conn, result, subject, source_label)
        if other is not None:
            group_key = other.get("po_number") or other.get("_source_file")
            if len(_line_multiset(result.get("line_items"))) < len(_line_multiset(other.get("line_items"))):
                # Fewer lines than the order it revises -> the customer restated
                # only the changes. Re-extract the COMPLETE revised order seeded
                # with the prior state so annotate_revisions doesn't read every
                # unrestated line as "Removed".
                seeded = _extract_modification(client, source_label, other, combined_text, fewshot_block, stop_event)
                if seeded is not None and "error" not in seeded:
                    result = seeded
                    result["_extraction_method"] = "text-mod"
            result["_group_override"] = group_key
            logger.info(f"{source_label}: grouped as a revision of PO {group_key}")
        elif not result.get("po_number") and _MODIFICATION_HINT.search(combined_text or ""):
            # Talks like a change to an existing order but names no PO we can
            # resolve — don't write a guessy fragment. Surface it for a human to
            # link on the Extraction Review page ("Revision of another PO").
            logger.info(f"{source_label}: looks like a modification but no resolvable target PO — flagging for review")
            result = {
                "_source_file": source_label, "_extraction_method": "text",
                "error": "modification — target PO unresolved",
            }

    if result is not None:
        result["_file_hash"] = file_hash
        result["source_received_at"] = _thread_received_at(messages)
        result["gmail_thread_id"] = thread_id
        results.append(result)
        extracted_keys.add((source_label, file_hash))
        if "error" not in result:
            # A successful extraction's thread-state write is DEFERRED to after the
            # publish (carried on the result as _thread_state, applied by _flush) —
            # writing it now would let a crash between here and the publish leave a
            # state row whose last_file_hash makes the next run skip an unpublished
            # PO, losing it silently.
            result["_thread_state"] = (thread_id, message_count, file_hash, True)
        elif result["error"] in (postgres_store.NOT_A_PO_ERROR, "modification — target PO unresolved"):
            # Settled outcomes for this thread content: 'not a purchase order', or a
            # modification we can't attach yet (a human links it on the review
            # page). Record the state so we don't re-pay every run — a new message
            # changes the hash and re-opens it.
            postgres_store.upsert_thread_state(pg_conn, thread_id, message_count, file_hash, was_po=False)
        # A real failure (credit/API error, timeout): write nothing — is_known() now
        # allows the retry, and no state row must block it.

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

    pg_conn = _connect(database_url)
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
            if len(matches) >= MAX_SEARCH_RESULTS:
                print(f"⚠️  {label}: hit the {MAX_SEARCH_RESULTS}-message search cap — "
                      "older threads under this label may be missing from this run "
                      "(raise MAX_SEARCH_RESULTS or narrow with the incremental cursor)")
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

        # A --full-backlog run ignores the time cursor, so a re-run after a timeout
        # would otherwise re-scan every thread from the top. Skip threads already
        # fully handled under the current schema (a Gmail fetch each, no Claude call,
        # but still minutes over thousands) so the backfill is resumable. A thread
        # that gained messages since is caught by the daily incremental run's cursor.
        if args.full_backlog:
            pg_conn = _ensure_connection(pg_conn, database_url)
            handled = postgres_store.handled_thread_ids(pg_conn)
            before = len(thread_ids)
            thread_ids = [t for t in thread_ids if t not in handled]
            if before != len(thread_ids):
                print(f"⏭️  Skipping {before - len(thread_ids)} thread(s) already processed — {len(thread_ids)} left")

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
        # Few-shot examples from human review decisions, fed into every extraction
        # and pre-extraction gate this run. Rebuilt each run so new corrections take
        # effect on the next run with no code change.
        fewshot_block = extraction_reviews.build_fewshot_block(pg_conn)
        if fewshot_block:
            print(f"🎓 Few-shot: {fewshot_block.count(chr(10)) } line(s) from human review decisions")
        stop_event = threading.Event()
        term_event = threading.Event()  # set by SIGTERM only — distinguishes a job
        # timeout / cancellation from the out-of-credits pause (both stop the loop).

        # A GitHub Actions job timeout (or a manual cancel) sends SIGTERM, whose
        # default handler exits immediately — skipping the tail _flush() and losing
        # the current un-checkpointed batch. Instead, flip the same stop flags the
        # out-of-credits path uses: the loop breaks at the next iteration boundary
        # (~one thread), the tail _flush() still runs, then we exit non-zero.
        def _on_sigterm(signum, frame):
            logger.warning("SIGTERM received (job timeout / cancellation) — will flush and exit after the current thread")
            term_event.set()
            stop_event.set()

        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _on_sigterm)

        pending = []          # results extracted since the last publish
        published_total = 0
        error_total = 0
        all_bad_dates = []
        skipped = 0
        # (source_file, file_hash) already extracted this run — guards against paying
        # twice when the same attachment rides on two different threads in one
        # checkpoint window (neither is_known yet, since neither is published).
        extracted_keys = set()

        def _flush() -> None:
            """Annotate + publish everything accumulated in `pending` (against the
            current full dataset), then clear it. Called every CHECKPOINT_EVERY
            threads and once at the end, so a mid-run kill loses at most one
            checkpoint's worth of paid extraction rather than the whole run.

            A transient DB failure here is retried FLUSH_MAX_ATTEMPTS times; `pending`
            is only cleared on success, so if every attempt fails the results stay
            queued for the next flush (and the exception still propagates, failing the
            run loudly rather than silently dropping paid work)."""
            nonlocal pending, published_total, error_total
            if not pending:
                return
            # Dedupe by (source_file, file_hash) — the same attachment can show up on
            # two threads; two such rows crash the batch publish's ON CONFLICT.
            deduped, seen_keys = [], set()
            for r in pending:
                key = (r.get("_source_file"), r.get("_file_hash"))
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(r)
            fresh_keys = seen_keys  # (source_file, file_hash) of everything we're about to publish
            # Deferred thread-state rows (see _process_thread), collected up front so a
            # retry doesn't lose the ones a partially-failed previous attempt already
            # consumed.
            thread_states = [r["_thread_state"] for r in deduped if r.get("_thread_state") is not None]

            def _po_key(r):
                return r.get("po_number") or r.get("_source_file")

            batch_po_numbers = [r.get("po_number") for r in deduped]
            batch_source_files = [r.get("_source_file") for r in deduped]

            for attempt in range(1, FLUSH_MAX_ATTEMPTS + 1):
                conn = None
                try:
                    # Every DB touch in this flush uses a freshly-opened, immediately-
                    # used, promptly-closed connection — the pattern _publish_to_postgres
                    # uses and the one that survives the GitHub Actions -> Neon link.
                    # A connection held across the checkpoint window (or even across the
                    # CPU-bound annotate_revisions below) reliably dies with "SSL
                    # connection has been closed unexpectedly".
                    conn = _connect(database_url)
                    # Only the revision history for POs in THIS batch — not the whole
                    # table. Drop any stored row a fresh result supersedes: a prior
                    # attempt that committed server-side but died before the client saw
                    # the ack leaves those rows here AND still in `deduped`; combining
                    # both would hand _publish_to_postgres two rows with the same
                    # (source_file, file_hash), which ON CONFLICT ... DO UPDATE cannot
                    # touch twice in one batch. The fresh copy is authoritative.
                    existing = [
                        r for r in postgres_store.get_related_dataset(
                            conn, batch_po_numbers, batch_source_files
                        )
                        if (r.get("_source_file"), r.get("_file_hash")) not in fresh_keys
                    ]
                    # Human "is this a revision?" calls, authoritative for grouping.
                    group_overrides = extraction_reviews.group_override_map(conn)
                    conn.close()
                    conn = None
                    # annotate_revisions() mutates line_items in place and is NOT
                    # idempotent (re-running over its own output re-injects "Removed"
                    # ghost rows). Work on a deep copy each attempt so the originals in
                    # `deduped` stay pristine for a retry and for the thread-state
                    # bookkeeping below.
                    batch = copy.deepcopy(deduped)
                    combined = existing + batch
                    if group_overrides:
                        for r in combined:
                            ov = group_overrides.get(r.get("gmail_thread_id")) or group_overrides.get(r.get("_source_file"))
                            if ov:
                                extraction_reviews.apply_group_override(r, ov)
                    combined.sort(key=lambda r: (r.get("po_date") or "9999", r.get("_source_file") or ""))
                    annotate_revisions(combined)
                    # Publish only the PO groups this batch touched; every other group's
                    # DELETE+reinsert would be pure churn.
                    touched = {_po_key(r) for r in batch}
                    to_publish = [r for r in combined if _po_key(r) in touched]
                    flush_bad_dates = _publish_to_postgres(to_publish, database_url)
                    # Now that these are persisted, record the deferred thread-state
                    # rows for the successful text-thread extractions. upsert is
                    # idempotent, so re-running these on a retry is harmless.
                    conn = _connect(database_url)
                    for ts in thread_states:
                        postgres_store.upsert_thread_state(conn, *ts)
                    conn.close()
                    conn = None
                    all_bad_dates.extend(flush_bad_dates)  # only on the success path
                    break
                except Exception as e:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    if attempt == FLUSH_MAX_ATTEMPTS:
                        logger.error(f"checkpoint publish failed after {attempt} attempt(s) — {e}")
                        raise
                    backoff = FLUSH_RETRY_BASE_SLEEP_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"checkpoint publish failed (attempt {attempt}/{FLUSH_MAX_ATTEMPTS}) — {e}; "
                        f"retrying in {backoff}s"
                    )
                    time.sleep(backoff)

            published_total += len(deduped)
            error_total += sum(1 for r in deduped if "error" in r)
            pending = []

        # mininterval=30: on a non-TTY (the Actions log) tqdm can't rewrite a line
        # with \r, so every update is its own line — throttle to ~one per 30s
        # instead of one per thread.
        for i, thread_id in enumerate(tqdm(thread_ids, unit="thread", ncols=80, mininterval=30), start=1):
            if stop_event.is_set():
                break
            try:
                pg_conn = _ensure_connection(pg_conn, database_url)
                access_token = gmail_client.get_valid_access_token(pg_conn, gmail_client_id, gmail_client_secret)
                results = _process_thread(
                    client, access_token, thread_id, reference_prices, pg_conn, stop_event,
                    mailbox_email, extracted_keys, fewshot_block,
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
            pending.extend(results)
            if i % CHECKPOINT_EVERY == 0 and pending:
                _flush()
                print(f"  💾 checkpoint — {published_total} result(s) published so far")

        _flush()  # the tail

        for source_file, field, value in all_bad_dates:
            print(f"⚠️  {source_file}: {field} = '{value}' (invalid date nulled out)")

        # A skipped thread's messages are necessarily before sync_started_at (it was
        # already found by this run's search) — advancing the cursor anyway would
        # permanently drop it from every future incremental search. Only advance when
        # nothing was skipped; a persistently-failing thread just means the same
        # (cheap-to-re-search) window gets rescanned next run, which is safe.
        cursor_safe_to_advance = skipped == 0
        if skipped:
            print(f"⚠️  {skipped} thread(s) failed before extraction (see log) — cursor NOT advanced, will retry next run")

        if term_event.is_set():
            # Cursor deliberately NOT advanced (we exit before mark_synced): the next
            # run re-scans the same window and skips what this run already published.
            print(f"\n⏹️  Stopped early on SIGTERM (job timeout / cancellation) — "
                  f"{published_total} result(s) published this run before stopping.")
            print("   Re-run the same command — already-processed threads are skipped automatically.")
            sys.exit(1)

        if stop_event.is_set():
            print(f"\n⏸️  Paused: ran out of API credits — {published_total} result(s) published this run before the pause.")
            print("   Add credits and rerun the same command — already-processed messages are skipped automatically.")
            sys.exit(3)

        print(f"📈 {published_total - error_total} extracted successfully, {error_total} error(s); {published_total} published.")

        if cursor_safe_to_advance:
            pg_conn = _ensure_connection(pg_conn, database_url)
            gmail_client.mark_synced(pg_conn, sync_started_at)
            print("✅ Done — cursor advanced.")
        else:
            print(f"✅ Done — cursor left as-is ({skipped} thread(s) to retry next run).")
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
