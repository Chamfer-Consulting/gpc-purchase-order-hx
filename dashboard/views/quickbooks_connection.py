"""
QuickBooks → Connection & Sync. Phase 4: page_header/section_card polish (structure
from Phase 1, which split the former single "QuickBooks" tab into this page plus
quickbooks_invoices.py's "Invoice Explorer").
"""

import secrets

import psycopg2
import streamlit as st

import qbo_client
from data import get_database_url
from ui_kit import page_header, section_card


def render(ctx) -> None:
    page_header(
        "Connection & Sync",
        "Connect to QuickBooks and sync invoice/item data — see Invoice Explorer for the raw synced data.",
    )
    if qbo_client.is_production():
        st.warning("Environment: **Production** — this pulls real invoice data.")
    else:
        st.info("Environment: **Sandbox** (test data only). Set `qbo_environment = \"production\"` to switch.")

    _conn = psycopg2.connect(get_database_url())
    try:
        connection = qbo_client.get_connection(_conn)
    finally:
        _conn.close()

    if connection is None:
        with section_card():
            st.info("Not connected to QuickBooks yet.")
            oauth_state = st.session_state.setdefault("qbo_oauth_state", secrets.token_urlsafe(16))
            st.link_button("Connect to QuickBooks", qbo_client.build_authorize_url(oauth_state))
        return

    with section_card():
        st.success(f"Connected — realm ID `{connection['realm_id']}` (since {connection['connected_at']}).")
        if connection.get("last_synced_at"):
            st.caption(f"Last synced: {connection['last_synced_at']} — next sync only pulls invoices changed since then.")
        else:
            st.caption("Never synced yet — the next sync pulls everything.")

        full_resync = st.checkbox("Full resync (ignore last-synced cursor, re-pull everything)")

        c1, c2 = st.columns(2)
        if c1.button("Sync invoices"):
            sync_conn = psycopg2.connect(get_database_url())
            try:
                with st.spinner("Pulling the product catalog from QuickBooks..."):
                    item_count = qbo_client.sync_items(sync_conn)
                with st.spinner("Pulling invoices from QuickBooks..."):
                    count = qbo_client.sync_invoices(sync_conn, full_resync=full_resync)
                st.success(f"Synced {item_count} catalog item(s) and {count} invoice(s).")
            except Exception as e:
                st.error(f"Sync failed: {e}")
            finally:
                sync_conn.close()
        if c2.button("Disconnect"):
            dc_conn = psycopg2.connect(get_database_url())
            try:
                qbo_client.disconnect(dc_conn)
            finally:
                dc_conn.close()
            st.rerun()
