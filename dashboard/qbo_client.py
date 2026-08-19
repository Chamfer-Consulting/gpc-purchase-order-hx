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
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
import streamlit as st
from psycopg2.extras import Json, execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from product_catalog import normalize_product, classify_qbo_item  # noqa: E402 — needs the sys.path insert above

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"


def is_production() -> bool:
    return st.secrets.get("qbo_environment", "sandbox") == "production"


def api_base() -> str:
    return "https://quickbooks.api.intuit.com" if is_production() else "https://sandbox-quickbooks.api.intuit.com"


def invoice_url(qbo_invoice_id: str) -> str:
    """Deep link to open this invoice directly in QuickBooks Online's own UI."""
    host = "qbo.intuit.com" if is_production() else "sandbox.qbo.intuit.com"
    return f"https://{host}/app/invoice?txnId={qbo_invoice_id}"


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
    """Updates the stored tokens for `realm_id`, or replaces the row entirely if this
    is a new/different realm (e.g. first connect, or switching sandbox<->production) —
    a routine refresh of the *same* realm preserves last_synced_at (the incremental
    sync cursor) rather than resetting it, since UPDATE touches only the token columns."""
    now = datetime.now(timezone.utc)
    access_expires = now + timedelta(seconds=tokens["expires_in"])
    refresh_expires = now + timedelta(seconds=tokens["x_refresh_token_expires_in"])
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE qbo_connection SET
                access_token = %s, refresh_token = %s,
                access_token_expires_at = %s, refresh_token_expires_at = %s,
                updated_at = now()
            WHERE realm_id = %s
            """,
            (tokens["access_token"], tokens["refresh_token"], access_expires, refresh_expires, realm_id),
        )
        if cur.rowcount == 0:
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
            "refresh_token_expires_at, connected_at, last_synced_at "
            "FROM qbo_connection ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "realm_id": row[0], "access_token": row[1], "refresh_token": row[2],
        "access_token_expires_at": row[3], "refresh_token_expires_at": row[4],
        "connected_at": row[5], "last_synced_at": row[6],
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


def fetch_all_invoices(access_token: str, realm_id: str, since: datetime | None = None) -> list[dict]:
    """Paginates QBO's Query API to pull Invoices — every one, or (for incremental
    syncs) only those updated after `since` (a timezone-aware datetime)."""
    invoices = []
    start_position = 1
    page_size = 1000
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    where = f" WHERE Metadata.LastUpdatedTime > '{since.isoformat()}'" if since else ""
    while True:
        query = f"SELECT * FROM Invoice{where} STARTPOSITION {start_position} MAXRESULTS {page_size}"
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


def fetch_all_items(access_token: str, realm_id: str) -> list[dict]:
    """Paginates QBO's Query API to pull every Item — the product master catalog.
    Always a full pull (no incremental cursor): the item list is small (a couple
    hundred rows across ~45 category groups), so there's no cost benefit to
    incremental sync, and a full pull can't miss an item quietly un-deleted.

    Explicitly includes inactive items (QBO's query API only returns Active=true
    by default) — most of the items historical invoice lines actually reference
    have since been deleted/deactivated in QBO, so leaving this off would silently
    exclude most of the catalog past invoices need to classify against."""
    items = []
    start_position = 1
    page_size = 1000
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    while True:
        query = (
            f"SELECT * FROM Item WHERE Active IN (true, false) "
            f"STARTPOSITION {start_position} MAXRESULTS {page_size}"
        )
        resp = requests.get(
            f"{api_base()}/v3/company/{realm_id}/query",
            headers=headers,
            params={"query": query, "minorversion": "65"},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"QuickBooks API error {resp.status_code}: {resp.text}")
        batch = resp.json().get("QueryResponse", {}).get("Item", [])
        items.extend(batch)
        if len(batch) < page_size:
            break
        start_position += page_size
    return items


def sync_items(conn) -> int:
    """Pulls the full Item list from QuickBooks and upserts it into qbo_items —
    the product master catalog that sync_invoices() matches invoice lines against
    by ID. Must run before sync_invoices() for that lookup to have fresh data."""
    access_token, realm_id = get_valid_access_token(conn)
    items = fetch_all_items(access_token, realm_id)
    if not items:
        return 0

    rows = []
    for it in items:
        name = it.get("Name", "")
        category, product_name, container_size = classify_qbo_item(name, it.get("Type"))
        rows.append((
            it.get("Id"), name, it.get("Type"), bool(it.get("Active", True)),
            it.get("UnitPrice"), it.get("Sku"), category, product_name, container_size,
        ))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO qbo_items (
                qbo_item_id, name, item_type, active, unit_price, sku,
                category, product_name, container_size, synced_at
            ) VALUES %s
            ON CONFLICT (qbo_item_id) DO UPDATE SET
                name           = EXCLUDED.name,
                item_type      = EXCLUDED.item_type,
                active         = EXCLUDED.active,
                unit_price     = EXCLUDED.unit_price,
                sku            = EXCLUDED.sku,
                category       = EXCLUDED.category,
                product_name   = EXCLUDED.product_name,
                container_size = EXCLUDED.container_size,
                synced_at      = now()
            """,
            rows,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
            page_size=500,
        )
    conn.commit()
    return len(items)


def sync_invoices(conn, full_resync: bool = False) -> int:
    """Pulls invoices from QuickBooks and upserts them into qbo_invoices.

    Incremental by default: only invoices updated since the last successful sync are
    fetched, via QBO's Metadata.LastUpdatedTime filter. Pass full_resync=True to ignore
    the cursor and re-pull everything (e.g. after a data-quality concern, or the first
    sync after switching sandbox<->production, which starts with no cursor anyway).
    """
    connection = get_connection(conn)
    since = None if full_resync else (connection or {}).get("last_synced_at")
    sync_started_at = datetime.now(timezone.utc)

    access_token, realm_id = get_valid_access_token(conn)
    invoices = fetch_all_invoices(access_token, realm_id, since=since)

    if invoices:
        rows = [
            (
                inv.get("Id"), inv.get("DocNumber"), (inv.get("CustomerRef") or {}).get("name"),
                inv.get("TxnDate") or None, inv.get("ShipDate") or None, inv.get("DueDate") or None,
                inv.get("TotalAmt"), inv.get("PrivateNote"), Json(inv),
            )
            for inv in invoices
        ]
        with conn.cursor() as cur:
            returned = execute_values(
                cur,
                """
                INSERT INTO qbo_invoices (
                    qbo_invoice_id, doc_number, customer_name, txn_date, ship_date,
                    due_date, total_amt, private_note, raw_json, synced_at
                ) VALUES %s
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
                RETURNING qbo_invoice_id, id
                """,
                rows,
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                page_size=200,
                fetch=True,
            )
            id_lookup = dict(returned)

            # Product master catalog (see sync_items()) — matching by QBO's stable
            # Item ID instead of re-parsing text. {qbo_item_id: (category, product_name,
            # container_size)}. Loaded once; falls back to normalize_product() text
            # matching for any item not in the catalog (sync_items() never run yet, or
            # the item was purged from QBO entirely) so nothing regresses.
            cur.execute("SELECT qbo_item_id, category, product_name, container_size FROM qbo_items")
            catalog = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

            item_rows = []
            invoice_ids = []
            for inv in invoices:
                invoice_id = id_lookup.get(inv.get("Id"))
                if invoice_id is None:
                    continue
                invoice_ids.append(invoice_id)
                for line in inv.get("Line") or []:
                    detail = line.get("SalesItemLineDetail")
                    if not detail:
                        continue
                    item_ref_obj = detail.get("ItemRef") or {}
                    item_ref_id = item_ref_obj.get("value")
                    item_ref = item_ref_obj.get("name", "")
                    description = line.get("Description", "")
                    unit_price = detail.get("UnitPrice")

                    catalog_entry = catalog.get(item_ref_id)
                    if catalog_entry is not None:
                        category, product_name, size = catalog_entry
                        is_sample = category == "sample"
                    else:
                        product_name, size, is_sample, _ = normalize_product(
                            f"{item_ref} {description}", unit_price=unit_price,
                        )
                        category = "sample" if is_sample else "product"

                    item_rows.append((
                        invoice_id, item_ref, description, product_name, size, is_sample,
                        detail.get("Qty"), unit_price, line.get("Amount"), item_ref_id, category,
                    ))

            if invoice_ids:
                cur.execute("DELETE FROM qbo_invoice_items WHERE invoice_id = ANY(%s)", (invoice_ids,))
            if item_rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO qbo_invoice_items (
                        invoice_id, item_raw, description, product_name, container_size,
                        is_sample, quantity, unit_price, line_total, qbo_item_id, category
                    ) VALUES %s
                    """,
                    item_rows,
                    page_size=500,
                )

    with conn.cursor() as cur:
        cur.execute("UPDATE qbo_connection SET last_synced_at = %s WHERE realm_id = %s", (sync_started_at, realm_id))
    conn.commit()
    return len(invoices)
