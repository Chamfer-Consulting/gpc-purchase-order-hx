"""
Links PO records to their original PDF's copy in a Google Shared Drive (the business
archives every PO PDF there on receipt) — Drive REST API v3 called directly via
`requests`, authenticated with a service account.

Deliberately not using google-api-python-client: its transitive protobuf/gRPC stack
requires protobuf>=6, which conflicts with Streamlit's pinned protobuf<6 (the same class
of dependency conflict that forced separate venvs for the extraction pipeline and
dashboard earlier in this project). Direct REST calls also match this project's existing
style (qbo_client.py) of calling APIs directly over pulling in heavy SDK wrappers.
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


def find_file_id(access_token: str, shared_drive_id: str, filename: str) -> str | None:
    """Searches the Shared Drive for a file with this exact name. Multiple matches
    (duplicate filenames) -> the most recently modified one — filenames are confirmed to
    match exactly in the normal case, so true duplicates are the rare edge, not the rule."""
    escaped = filename.replace("'", "\\'")
    resp = requests.get(
        DRIVE_API,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": f"name = '{escaped}' and trashed = false",
            "corpora": "drive",
            "driveId": shared_drive_id,
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


def sync_drive_links(conn) -> dict:
    """For every PO not yet linked, search the Shared Drive by its source_file name and
    record the match. Sequential requests — Drive's default read quota comfortably covers
    a ~1300-file backfill, and this only runs occasionally: once a PO is linked it's never
    re-searched (drive_file_id IS NULL is the incremental filter), and a not-found PO
    stays eligible for retry on the next sync in case the file gets archived later."""
    shared_drive_id = st.secrets["gdrive_shared_drive_id"]
    access_token = _access_token()

    with conn.cursor() as cur:
        cur.execute("SELECT id, source_file FROM purchase_orders WHERE drive_file_id IS NULL")
        rows = cur.fetchall()

    linked = not_found = 0
    with conn.cursor() as cur:
        for po_id, source_file in rows:
            file_id = find_file_id(access_token, shared_drive_id, source_file)
            if file_id:
                cur.execute(
                    "UPDATE purchase_orders SET drive_file_id = %s, drive_synced_at = now() WHERE id = %s",
                    (file_id, po_id),
                )
                linked += 1
            else:
                not_found += 1
    conn.commit()

    return {"linked": linked, "not_found": not_found, "total_checked": len(rows)}


def file_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"
