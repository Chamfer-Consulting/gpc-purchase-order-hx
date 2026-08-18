"""
QuickBooks Online integration — Phase 1: OAuth connect + raw invoice pull.

Environment (sandbox vs production) is controlled by the `qbo_environment` secret
("sandbox"/"production", defaults to "sandbox" if unset — safe default). Switching
environments also means switching qbo_client_id/qbo_client_secret to the matching
Development or Production keys from Intuit's app dashboard; a token issued under one
environment's credentials won't authenticate against the other's API base, so reconnect
(disconnect + Connect again) after changing qbo_environment.
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
import streamlit as st
from psycopg2.extras import Json

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"


def is_production() -> bool:
    return st.secrets.get("qbo_environment", "sandbox") == "production"


def api_base() -> str:
    return "https://quickbooks.api.intuit.com" if is_production() else "https://sandbox-quickbooks.api.intuit.com"


def _creds():
    return st.secrets["qbo_client_id"], st.secrets["qbo_client_secret"], st.secrets["qbo_redirect_uri"]


def build_authorize_url(state: str) -> str:
    client_id, _, redirect_uri = _creds()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _store_tokens(conn, realm_id: str, tokens: dict) -> None:
    now = datetime.now(timezone.utc)
    access_expires = now + timedelta(seconds=tokens["expires_in"])
    refresh_expires = now + timedelta(seconds=tokens["x_refresh_token_expires_in"])
    with conn.cursor() as cur:
        cur.execute("DELETE FROM qbo_connection")
        cur.execute(
            """
            INSERT INTO qbo_connection (
                realm_id, access_token, refresh_token,
                access_token_expires_at, refresh_token_expires_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (realm_id, tokens["access_token"], tokens["refresh_token"], access_expires, refresh_expires),
        )
    conn.commit()


def exchange_code_for_tokens(conn, code: str, realm_id: str) -> None:
    client_id, client_secret, redirect_uri = _creds()
    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"QuickBooks token exchange failed {resp.status_code}: {resp.text}")
    _store_tokens(conn, realm_id, resp.json())


def _refresh(conn, realm_id: str, refresh_token: str) -> str:
    client_id, client_secret, _ = _creds()
    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"QuickBooks token refresh failed {resp.status_code}: {resp.text}")
    tokens = resp.json()
    _store_tokens(conn, realm_id, tokens)
    return tokens["access_token"]


def get_connection(conn) -> dict | None:
    """Returns the stored qbo_connection row as a dict, or None if never connected."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT realm_id, access_token, refresh_token, access_token_expires_at, "
            "refresh_token_expires_at, connected_at FROM qbo_connection ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "realm_id": row[0], "access_token": row[1], "refresh_token": row[2],
        "access_token_expires_at": row[3], "refresh_token_expires_at": row[4], "connected_at": row[5],
    }


def get_valid_access_token(conn) -> tuple[str, str]:
    """Returns (access_token, realm_id), refreshing first if the access token is near expiry."""
    connection = get_connection(conn)
    if connection is None:
        raise RuntimeError("Not connected to QuickBooks yet.")
    now = datetime.now(timezone.utc)
    if connection["access_token_expires_at"] <= now + timedelta(minutes=5):
        access_token = _refresh(conn, connection["realm_id"], connection["refresh_token"])
    else:
        access_token = connection["access_token"]
    return access_token, connection["realm_id"]


def disconnect(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM qbo_connection")
    conn.commit()


def fetch_all_invoices(access_token: str, realm_id: str) -> list[dict]:
    """Paginates QBO's Query API to pull every Invoice."""
    invoices = []
    start_position = 1
    page_size = 1000
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    while True:
        query = f"SELECT * FROM Invoice STARTPOSITION {start_position} MAXRESULTS {page_size}"
        resp = requests.get(
            f"{api_base()}/v3/company/{realm_id}/query",
            headers=headers,
            params={"query": query, "minorversion": "65"},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"QuickBooks API error {resp.status_code}: {resp.text}")
        batch = resp.json().get("QueryResponse", {}).get("Invoice", [])
        invoices.extend(batch)
        if len(batch) < page_size:
            break
        start_position += page_size
    return invoices


def sync_invoices(conn) -> int:
    access_token, realm_id = get_valid_access_token(conn)
    invoices = fetch_all_invoices(access_token, realm_id)
    with conn.cursor() as cur:
        for inv in invoices:
            cur.execute(
                """
                INSERT INTO qbo_invoices (
                    qbo_invoice_id, doc_number, customer_name, txn_date, ship_date,
                    due_date, total_amt, private_note, raw_json, synced_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (qbo_invoice_id) DO UPDATE SET
                    doc_number    = EXCLUDED.doc_number,
                    customer_name = EXCLUDED.customer_name,
                    txn_date      = EXCLUDED.txn_date,
                    ship_date     = EXCLUDED.ship_date,
                    due_date      = EXCLUDED.due_date,
                    total_amt     = EXCLUDED.total_amt,
                    private_note  = EXCLUDED.private_note,
                    raw_json      = EXCLUDED.raw_json,
                    synced_at     = now()
                """,
                (
                    inv.get("Id"),
                    inv.get("DocNumber"),
                    (inv.get("CustomerRef") or {}).get("name"),
                    inv.get("TxnDate") or None,
                    inv.get("ShipDate") or None,
                    inv.get("DueDate") or None,
                    inv.get("TotalAmt"),
                    inv.get("PrivateNote"),
                    Json(inv),
                ),
            )
    conn.commit()
    return len(invoices)
