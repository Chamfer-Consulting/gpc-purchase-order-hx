"""
Gmail integration — OAuth connect plus read-only label/message/attachment access,
used by the dashboard's one-time "Connect Gmail" flow and by the cloud extraction
pipeline (run_cloud_extraction.py, run manually or via a scheduled GitHub Action).

Unlike qbo_client.py, credentials (client_id/client_secret/redirect_uri) are passed
in as explicit arguments rather than read internally from st.secrets — this module
is imported by both the Streamlit dashboard (passing st.secrets[...]) and a plain
CLI/GitHub Actions script with no Streamlit installed (passing os.environ[...]), so
it must not hard-depend on Streamlit itself (see GMAIL_SETUP.md / the plan this was
built from). Pure requests-based REST calls throughout, same reasoning as qbo_client.py:
avoids the heavy, protobuf-pinned google-api-python-client SDK, which conflicts
with Streamlit's pinned protobuf<6.
"""

import base64
import html as html_module
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


# ── OAuth ────────────────────────────────────────────────────────────────────────

def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "offline",  # required for Google to ever issue a refresh_token
        "prompt": "consent",       # forces a fresh refresh_token even on a reconnect
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _store_tokens(conn, email_address: str, tokens: dict) -> None:
    """Updates the stored connection, or inserts a new row on first connect. Google's
    refresh grant normally omits refresh_token entirely (only the initial
    authorization-code exchange returns one, and only when access_type=offline was
    requested) — never overwrite a stored refresh_token with a missing one; a routine
    refresh only touches the access token."""
    now = datetime.now(timezone.utc)
    access_expires = now + timedelta(seconds=tokens.get("expires_in", 3600))
    refresh_token = tokens.get("refresh_token")

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM gmail_connection ORDER BY id DESC LIMIT 1")
        existing = cur.fetchone()

        if existing is None:
            if not refresh_token:
                raise RuntimeError(
                    "Google didn't return a refresh token on this exchange, and there's "
                    "no existing connection to fall back to — this shouldn't happen on a "
                    "fresh consent (access_type=offline + prompt=consent are always sent "
                    "by build_authorize_url); try connecting again."
                )
            cur.execute(
                """
                INSERT INTO gmail_connection (
                    email_address, access_token, refresh_token, access_token_expires_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (email_address, tokens["access_token"], refresh_token, access_expires),
            )
        elif refresh_token:
            cur.execute(
                """
                UPDATE gmail_connection SET
                    email_address = %s, access_token = %s, refresh_token = %s,
                    access_token_expires_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (email_address, tokens["access_token"], refresh_token, access_expires, existing[0]),
            )
        else:
            cur.execute(
                """
                UPDATE gmail_connection SET
                    access_token = %s, access_token_expires_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (tokens["access_token"], access_expires, existing[0]),
            )
    conn.commit()


def exchange_code_for_tokens(conn, client_id: str, client_secret: str, redirect_uri: str, code: str) -> None:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Gmail token exchange failed {resp.status_code}: {resp.text}")
    tokens = resp.json()

    profile_resp = requests.get(
        f"{GMAIL_API}/profile", headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=30,
    )
    email_address = profile_resp.json().get("emailAddress", "") if profile_resp.ok else ""

    _store_tokens(conn, email_address, tokens)


def _refresh(conn, client_id: str, client_secret: str, refresh_token: str, email_address: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Gmail token refresh failed {resp.status_code}: {resp.text}")
    tokens = resp.json()
    _store_tokens(conn, email_address, tokens)
    return tokens["access_token"]


def get_connection(conn) -> dict | None:
    """Returns the stored gmail_connection row as a dict, or None if never connected."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email_address, access_token, refresh_token, access_token_expires_at, "
            "connected_at, updated_at, last_synced_at FROM gmail_connection ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "email_address": row[0], "access_token": row[1], "refresh_token": row[2],
        "access_token_expires_at": row[3], "connected_at": row[4],
        "updated_at": row[5], "last_synced_at": row[6],
    }


def get_valid_access_token(conn, client_id: str, client_secret: str) -> str:
    """Returns a valid access token, refreshing first if the stored one is near expiry."""
    connection = get_connection(conn)
    if connection is None:
        raise RuntimeError("Not connected to Gmail yet.")
    now = datetime.now(timezone.utc)
    if connection["access_token_expires_at"] <= now + timedelta(minutes=5):
        return _refresh(conn, client_id, client_secret, connection["refresh_token"], connection["email_address"])
    return connection["access_token"]


def disconnect(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM gmail_connection")
    conn.commit()


def mark_synced(conn, synced_at: datetime) -> None:
    """Updates the incremental-scan cursor after a successful ingestion run."""
    with conn.cursor() as cur:
        cur.execute("UPDATE gmail_connection SET last_synced_at = %s", (synced_at,))
    conn.commit()


# ── Labels / search / message content ──────────────────────────────────────────────

def list_labels(access_token: str) -> list[dict]:
    """Returns every label in the account ({'id', 'name', 'type'}, among other
    fields) — used to confirm the exact label names/ids Gmail's API sees, which
    aren't always byte-identical to how the Gmail UI displays them (especially for
    nested labels like 'PO/Get Fresh')."""
    resp = requests.get(f"{GMAIL_API}/labels", headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
    return resp.json().get("labels", [])


def resolve_label_id(access_token: str, label_name: str) -> str | None:
    """Looks up a label's stable ID by its exact display name (via list_labels), or
    None if no label with that name exists. Needed because search_messages()
    filters by ID, not name — see its docstring."""
    for label in list_labels(access_token):
        if label.get("name") == label_name:
            return label["id"]
    return None


def search_messages(
    access_token: str, label_id: str, extra_query: str | None = None, max_results: int = 50
) -> list[tuple[str, str]]:
    """Returns (message_id, thread_id) pairs carrying the given label (by ID, via
    the structured labelIds parameter — NOT Gmail's q=label:"..." search syntax,
    which was found live to silently return zero results for label names containing
    an apostrophe or ampersand, e.g. "Anthony Marano's (AMC)" and "Marillac House
    (Tramaine & Holly)" — hundreds of real messages under those two labels were
    completely invisible to every q=label: search despite returning no error at
    all). Use resolve_label_id() to turn a display name into the ID this expects.

    thread_id (Gmail's messages.list response already includes it per entry, no
    extra API call) lets a caller dedupe/group matched messages by thread — see
    get_thread() for fetching a thread's full content once grouped.

    extra_query, if given, is ANDed in via Gmail's q parameter (e.g. 'after:169...')
    — safe to combine with labelIds since it never needs to contain the label name
    itself. Paginates via nextPageToken up to max_results."""
    results = []
    page_token = None
    headers = {"Authorization": f"Bearer {access_token}"}
    while len(results) < max_results:
        params = {"labelIds": label_id, "maxResults": min(100, max_results - len(results))}
        if extra_query:
            params["q"] = extra_query
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(f"{GMAIL_API}/messages", headers=headers, params=params, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
        body = resp.json()
        results.extend((m["id"], m["threadId"]) for m in body.get("messages", []))
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return results


def get_thread(access_token: str, thread_id: str) -> dict:
    """Full thread detail (format=full) — {'id', 'historyId', 'messages': [...]},
    each message in the exact same shape get_message() returns (message_headers()/
    extract_body_and_attachments() work unmodified on each one), already in
    chronological order. One API call for the whole conversation instead of one per
    message — used to extract a text-only thread (no PDF attachment anywhere in it)
    as a single unit reflecting the full back-and-forth, not just one message."""
    resp = requests.get(
        f"{GMAIL_API}/threads/{thread_id}", headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"}, timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
    return resp.json()


def get_message(access_token: str, message_id: str) -> dict:
    """Full message detail (format=full) — headers, MIME body parts, and attachment
    metadata (id/filename/size — not the attachment bytes themselves, see
    get_attachment for that)."""
    resp = requests.get(
        f"{GMAIL_API}/messages/{message_id}", headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"}, timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
    return resp.json()


def get_attachment(access_token: str, message_id: str, attachment_id: str) -> bytes:
    resp = requests.get(
        f"{GMAIL_API}/messages/{message_id}/attachments/{attachment_id}",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
    data = resp.json()["data"]
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def attachment_bytes(access_token: str, message_id: str, att: dict) -> bytes:
    """Raw bytes for one extract_body_and_attachments() entry — from the inline
    base64 'data' when Gmail returned it that way (small attachments), otherwise a
    get_attachment() fetch by id."""
    if att.get("data"):
        d = att["data"]
        return base64.urlsafe_b64decode(d + "=" * (-len(d) % 4))
    return get_attachment(access_token, message_id, att["attachment_id"])


def message_headers(message: dict) -> dict:
    """{header_name_lowercased: value} for a get_message() result's headers."""
    return {h.get("name", "").lower(): h.get("value") for h in message.get("payload", {}).get("headers", [])}


def _walk_parts(payload: dict):
    """Yields every leaf MIME part (the payload itself if it has no sub-parts)."""
    parts = payload.get("parts")
    if not parts:
        yield payload
        return
    for p in parts:
        yield from _walk_parts(p)


def _html_to_text(raw_html: str) -> str:
    """Crude HTML->text fallback for HTML-only email bodies: strip tags, unescape
    entities, collapse whitespace. Good enough for feeding to Claude (which needs
    readable content, not pixel-perfect formatting) without pulling in a new
    dependency for a path most PO emails won't even hit — plain-text bodies are the
    common case, this only kicks in when no text/plain part exists at all."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


_PDF_NAME = re.compile(r"\.pdf\s*$", re.I)
# MIME types a PDF attachment legitimately arrives under. Get Fresh's PO system
# (and plenty of other ERPs) attach the PDF as application/octet-stream and rely on
# the .pdf extension; some senders use application/x-pdf or a download-forcing type,
# or leave it blank. So: trust a ".pdf" filename, but only when the declared type
# is one of these generic/blank ones or actually application/pdf — never for an
# image/*, text/*, message/rfc822, etc. that merely happens to be named *.pdf.
_PDF_MIME_OK = {
    "application/pdf", "application/x-pdf", "application/acrobat",
    "applications/vnd.pdf", "text/pdf", "text/x-pdf",
    "application/octet-stream", "binary/octet-stream",
    "application/download", "application/force-download", "",
}


def _looks_like_pdf_part(filename: str, mime_type: str) -> bool:
    if mime_type == "application/pdf":
        return True
    return bool(_PDF_NAME.search(filename)) and mime_type.lower() in _PDF_MIME_OK


def extract_body_and_attachments(message: dict) -> tuple[str, list[dict]]:
    """From a get_message() result: returns (body_text, attachments), where
    attachments is [{'filename', 'attachment_id', 'data', 'mime_type', 'size'}, ...]
    for every PDF-looking part (see _looks_like_pdf_part — not just an exact
    application/pdf type). Exactly one of 'attachment_id' / 'data' is set: Gmail
    returns small attachments inline as base64 'data' with no attachmentId.
    body_text prefers text/plain parts, falling back to a crude strip of text/html
    when no plain-text part exists."""
    payload = message.get("payload", {})
    plain_parts, html_parts, attachments = [], [], []

    for part in _walk_parts(payload):
        filename = part.get("filename") or ""
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})

        if filename and _looks_like_pdf_part(filename, mime_type) and (body.get("attachmentId") or body.get("data")):
            attachments.append({
                "filename": filename,
                "attachment_id": body.get("attachmentId"),
                "data": body.get("data"),  # inline base64url when there's no attachmentId
                "mime_type": mime_type, "size": body.get("size", 0),
            })
        elif not filename and body.get("data"):
            data = body["data"]
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)

    if plain_parts:
        text = "\n".join(plain_parts).strip()
    elif html_parts:
        text = "\n".join(_html_to_text(h) for h in html_parts).strip()
    else:
        text = ""

    return text, attachments
