"""
QuickBooks → Connection & Sync. Phase 4: page_header/section_card polish (structure
from Phase 1, which split the former single "QuickBooks" tab into this page plus
quickbooks_invoices.py's "Invoice Explorer").
"""

import secrets
from datetime import datetime, timezone

import psycopg2
import streamlit as st

import qbo_client
from data import get_database_url
from ui_kit import page_header, section_card

_REQUIRED_SECRETS = ("qbo_client_id", "qbo_client_secret", "qbo_redirect_uri")


def render(ctx) -> None:
    page_header(
        "Connection & Sync",
        "Connect to QuickBooks and sync invoice/item data — see Invoice Explorer for the raw synced data.",
    )

    missing = [k for k in _REQUIRED_SECRETS if not st.secrets.get(k)]
    if missing:
        st.info(
            "QuickBooks isn't configured. Add "
            + ", ".join(f"`{k}`" for k in missing)
            + " to `.streamlit/secrets.toml` to enable this section."
        )
        return

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

        # Scheduled headless sync heartbeat (run_qbo_sync.py / qbo_sync.yml).
        auto_at = connection.get("auto_synced_at")
        auto_err = connection.get("auto_sync_error")
        if auto_err:
            st.error(
                f"Automatic daily sync is failing: {auto_err}\n\n"
                "If this is a reauthorisation error, reconnect below and run a full resync."
            )
        elif auto_at:
            age_h = (datetime.now(timezone.utc) - auto_at).total_seconds() / 3600
            if age_h > 36:
                st.warning(f"Automatic daily sync last succeeded {age_h:.0f}h ago — the schedule may be stalled.")
            else:
                st.caption(f"✅ Automatic daily sync: last ran {auto_at:%Y-%m-%d %H:%M UTC} ({age_h:.0f}h ago).")
        else:
            st.caption("Automatic daily sync: not yet run (enable the `Sync QuickBooks` GitHub Action).")

        # Warn before the refresh token actually expires (~100 days from issue; it also
        # rotates on every successful refresh, so an active connection keeps extending).
        refresh_exp = connection.get("refresh_token_expires_at")
        if refresh_exp is not None:
            days_left = (refresh_exp - datetime.now(timezone.utc)).days
            if days_left < 0:
                st.error("The connection has expired — disconnect and connect again, then run a full resync.")
            elif days_left <= 14:
                st.warning(f"The connection expires in ~{days_left} day(s) — sync (or reconnect) soon to keep it alive.")

        full_resync = st.checkbox("Full resync (ignore last-synced cursor, re-pull everything)")

        c1, c2 = st.columns(2)
        if c1.button("Sync invoices"):
            sync_conn = psycopg2.connect(get_database_url())
            try:
                with st.spinner("Pulling the product catalog from QuickBooks..."):
                    item_count = qbo_client.sync_items(sync_conn)
                with st.spinner("Pulling invoices from QuickBooks..."):
                    result = qbo_client.sync_invoices(sync_conn, full_resync=full_resync)
                msg = f"Synced {item_count} catalog item(s) and {result['synced']} invoice(s)."
                if result.get("deleted"):
                    msg += f" Removed {result['deleted']} invoice(s) no longer in QuickBooks."
                st.success(msg)
            except qbo_client.QBOReauthRequired as e:
                st.error(str(e))
                st.link_button(
                    "Reconnect to QuickBooks",
                    qbo_client.build_authorize_url(st.session_state.get("qbo_oauth_state", secrets.token_urlsafe(16))),
                )
            except Exception as e:
                st.error(f"Sync failed: {e}")
            finally:
                sync_conn.close()

        with c2.popover("Disconnect"):
            st.caption("Disconnecting clears the tokens — you'll need to reconnect and run a full resync.")
            if st.checkbox("Yes, disconnect QuickBooks", key="qbo_disconnect_confirm"):
                if st.button("Disconnect now", type="primary", key="qbo_disconnect_go"):
                    dc_conn = psycopg2.connect(get_database_url())
                    try:
                        qbo_client.disconnect(dc_conn)
                    finally:
                        dc_conn.close()
                    st.rerun()
