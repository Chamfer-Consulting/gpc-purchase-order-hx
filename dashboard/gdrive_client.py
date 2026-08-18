"""
Links PO records to their original PDF's copy in a private Google Drive folder (the
business's email-attachment auto-download tool saves every PO PDF there on receipt) —
Drive REST API v3 called directly via `requests`, authenticated with a service account.

Deliberately not using google-api-python-client: its transitive protobuf/gRPC stack
requires protobuf>=6, which conflicts with Streamlit's pinned protobuf<6 (the same class
of dependency conflict that forced separate venvs for the extraction pipeline and
dashboard earlier in this project). Direct REST calls also match this project's existing
style (qbo_client.py) of calling APIs directly over pulling in heavy SDK wrappers.

A regular (non-Shared-Drive) folder, since the attachment-download tool doesn't work
against Shared Drives — the service account is instead granted access the normal way,
by sharing that specific folder with its client_email as a Viewer.
"""

import requests
import streamlit as st
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_API = "https://www.googleapis.com/drive/v3/files"


def _access_token() -> str:
    info = dict(st.secrets["gdrive_service_account"])
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    credentials.refresh(GoogleAuthRequest())
    return credentials.token


def find_file_id(access_token: str, folder_id: str, filename: str) -> str | None:
    """Searches the given folder for a file with this exact name. Multiple matches
    (duplicate filenames) -> the most recently modified one — filenames are confirmed to
    match exactly in the normal case, so true duplicates are the rare edge, not the rule."""
    escaped = filename.replace("'", "\\'")
    resp = requests.get(
        DRIVE_API,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": f"name = '{escaped}' and '{folder_id}' in parents and trashed = false",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "fields": "files(id,name,modifiedTime)",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Google Drive API error {resp.status_code}: {resp.text}")
    files = resp.json().get("files", [])
    if not files:
        return None
    files.sort(key=lambda f: f.get("modifiedTime", ""), reverse=True)
    return files[0]["id"]


DEFAULT_BATCH_LIMIT = 150  # per call — one Drive API round trip per PO (~0.2-0.3s each);
                           # a full ~1300-PO backfill in one call could run 5+ minutes with
                           # no visible feedback and risks a proxy/request timeout on
                           # Streamlit Cloud. Bounding it keeps each click fast and safe;
                           # the caller reruns for however many batches are left.


def sync_drive_links(conn, limit: int = DEFAULT_BATCH_LIMIT, progress=None) -> dict:
    """For up to `limit` not-yet-linked POs, search the Drive folder by source_file name
    and record the match. `progress(i, total)`, if given, is called after each lookup so
    the caller can render a live progress bar instead of one long silent wait.

    Sequential requests — Drive's default read quota comfortably covers this. Once a PO
    is linked it's never re-searched (drive_file_id IS NULL is the incremental filter);
    a not-found PO stays eligible for retry on a later sync in case the file shows up
    afterward."""
    folder_id = st.secrets["gdrive_folder_id"]
    access_token = _access_token()

    with conn.cursor() as cur:
        cur.execute("SELECT id, source_file FROM purchase_orders WHERE drive_file_id IS NULL LIMIT %s", (limit,))
        rows = cur.fetchall()

    linked = not_found = 0
    with conn.cursor() as cur:
        for i, (po_id, source_file) in enumerate(rows, start=1):
            file_id = find_file_id(access_token, folder_id, source_file)
            if file_id:
                cur.execute(
                    "UPDATE purchase_orders SET drive_file_id = %s, drive_synced_at = now() WHERE id = %s",
                    (file_id, po_id),
                )
                linked += 1
            else:
                not_found += 1
            if progress:
                progress(i, len(rows))
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM purchase_orders WHERE drive_file_id IS NULL AND error IS NULL")
        remaining = cur.fetchone()[0]

    return {"linked": linked, "not_found": not_found, "total_checked": len(rows), "remaining": remaining}


def file_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"
