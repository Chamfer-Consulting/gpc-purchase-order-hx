"""
✉️ Email Ingestion → Connection. One-time Gmail OAuth connect (same shape as
QuickBooks' Connection & Sync page — see quickbooks_connection.py) plus a label
lister and a manual search test, so the exact label name(s) Gmail's API sees can be
confirmed before wiring up GMAIL_LABELS config. The cloud extraction pipeline
itself (run_cloud_extraction.py) is a separate script, not run from here — GitHub's
own Actions UI covers manual/automatic runs (see the plan).
"""

import secrets

import psycopg2
import streamlit as st

import gmail_client
from data import get_database_url
from ui_kit import page_header, section_card


def _creds():
    return st.secrets["gmail_client_id"], st.secrets["gmail_client_secret"], st.secrets["gmail_redirect_uri"]


def render(ctx) -> None:
    page_header(
        "Email Ingestion",
        "Connect Gmail so the cloud extraction pipeline can read labeled PO emails — "
        "attachments and body text alike. This page only covers the one-time connection "
        "and confirming label names; see GMAIL_SETUP.md for automatic/manual run setup.",
    )

    client_id, client_secret, redirect_uri = _creds()

    _conn = psycopg2.connect(get_database_url())
    try:
        connection = gmail_client.get_connection(_conn)
    finally:
        _conn.close()

    if connection is None:
        with section_card():
            st.info("Not connected to Gmail yet.")
            # Prefixed (not just a bare random token) so app.py's OAuth callback can
            # tell a Gmail redirect apart from a QuickBooks one — Google's callback
            # never carries realmId, which is what QBO's branch keys on, but Gmail
            # needs its own positive signal rather than an "else".
            oauth_state = st.session_state.setdefault(
                "gmail_oauth_state", f"gmail_connect:{secrets.token_urlsafe(16)}"
            )
            st.link_button(
                "✉️ Connect Gmail", gmail_client.build_authorize_url(client_id, redirect_uri, oauth_state),
            )
        return

    with section_card():
        st.success(f"Connected — **{connection['email_address']}** (since {connection['connected_at']}).")
        if connection.get("last_synced_at"):
            st.caption(f"Last synced: {connection['last_synced_at']}")
        else:
            st.caption("Never synced yet.")
        if st.button("Disconnect"):
            dc_conn = psycopg2.connect(get_database_url())
            try:
                gmail_client.disconnect(dc_conn)
            finally:
                dc_conn.close()
            st.rerun()

    with section_card("🏷️ Labels", "Confirm the exact label name(s) Gmail's API sees — use these for GMAIL_LABELS config."):
        if st.button("List labels"):
            token_conn = psycopg2.connect(get_database_url())
            try:
                access_token = gmail_client.get_valid_access_token(token_conn, client_id, client_secret)
            finally:
                token_conn.close()
            try:
                labels = gmail_client.list_labels(access_token)
            except Exception as e:
                st.error(f"Couldn't list labels: {e}")
            else:
                user_labels = sorted((l["name"] for l in labels if l.get("type") == "user"), key=str.lower)
                if user_labels:
                    st.write(f"{len(user_labels)} label(s):")
                    st.code("\n".join(user_labels))
                else:
                    st.info("No user-created labels found on this account.")

    with section_card(
        "🔎 Test search",
        "Search by label (plus optional Gmail query syntax) to confirm matching works, without extracting anything yet.",
    ):
        label = st.text_input('Label name (exact, e.g. "PO/Get Fresh")', key="gmail_test_label")
        extra_query = st.text_input("Additional query (optional, Gmail search syntax)", key="gmail_test_query")
        if st.button("Search"):
            if not label:
                st.warning("Enter a label name first.")
            else:
                query = f'label:"{label}"' + (f" {extra_query}" if extra_query else "")
                token_conn = psycopg2.connect(get_database_url())
                try:
                    access_token = gmail_client.get_valid_access_token(token_conn, client_id, client_secret)
                finally:
                    token_conn.close()
                try:
                    message_ids = gmail_client.search_messages(access_token, query, max_results=25)
                except Exception as e:
                    st.error(f"Search failed: {e}")
                else:
                    if not message_ids:
                        st.info(f"No messages found for: `{query}`")
                    else:
                        st.write(f"{len(message_ids)} message(s) found for `{query}`:")
                        rows = []
                        for mid in message_ids:
                            msg = gmail_client.get_message(access_token, mid)
                            headers = gmail_client.message_headers(msg)
                            body_text, attachments = gmail_client.extract_body_and_attachments(msg)
                            rows.append({
                                "Subject": headers.get("subject") or "(no subject)",
                                "From": headers.get("from") or "",
                                "Date": headers.get("date") or "",
                                "Has PDF attachment": "Yes" if attachments else "No",
                                "Attachment(s)": ", ".join(a["filename"] for a in attachments),
                                "Body preview": (body_text[:80] + "…") if len(body_text) > 80 else body_text,
                            })
                        st.dataframe(rows, width="stretch")
