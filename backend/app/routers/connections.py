"""Gmail + QuickBooks connection status / connect / disconnect. The OAuth
*callbacks* (browser redirects from Google / Intuit) are in routers/oauth.py and
carry no bearer token; everything here requires one."""

import gmail_client  # repo root, via app.reuse
import qbo_client  # dashboard/, via app.reuse
from fastapi import APIRouter, Depends, HTTPException

from .. import oauth_state
from ..auth import AuthedUser, current_user
from ..config import get_settings
from ..reused_db import reused_conn

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _iso(v) -> str | None:
    return v.isoformat() if v is not None and hasattr(v, "isoformat") else v


@router.get("")
def status(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        g = gmail_client.get_connection(conn)
        q = qbo_client.get_connection(conn)
    return {
        "gmail": None
        if g is None
        else {
            "email_address": g["email_address"],
            "connected_at": _iso(g["connected_at"]),
            "last_synced_at": _iso(g["last_synced_at"]),
        },
        "qbo": None
        if q is None
        else {
            "realm_id": q["realm_id"],
            "connected_at": _iso(q["connected_at"]),
            "last_synced_at": _iso(q["last_synced_at"]),
            "refresh_token_expires_at": _iso(q.get("refresh_token_expires_at")),
            "auto_synced_at": _iso(q.get("auto_synced_at")),
            "auto_sync_error": q.get("auto_sync_error"),
            "environment": "production" if qbo_client.is_production() else "sandbox",
        },
    }


@router.get("/gmail/authorize")
def gmail_authorize(_: AuthedUser = Depends(current_user)) -> dict:
    s = get_settings()
    if not (s.gmail_client_id and s.gmail_redirect_uri):
        raise HTTPException(503, "Gmail OAuth is not configured (GMAIL_CLIENT_ID / GMAIL_REDIRECT_URI).")
    st = oauth_state.issue("gmail")
    return {"url": gmail_client.build_authorize_url(s.gmail_client_id, s.gmail_redirect_uri, st)}


@router.get("/qbo/authorize")
def qbo_authorize(_: AuthedUser = Depends(current_user)) -> dict:
    st = oauth_state.issue("qbo")
    try:
        return {"url": qbo_client.build_authorize_url(st)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.post("/gmail/disconnect")
def gmail_disconnect(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        gmail_client.disconnect(conn)
    return {"ok": True}


@router.post("/qbo/disconnect")
def qbo_disconnect(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        qbo_client.disconnect(conn)
    return {"ok": True}


@router.post("/qbo/sync")
def qbo_sync(full_resync: bool = False, _: AuthedUser = Depends(current_user)) -> dict:
    """On-demand QuickBooks sync. The daily job (run_qbo_sync.py) is the norm; this
    is the 'sync now' button."""
    with reused_conn() as conn:
        try:
            items = qbo_client.sync_items(conn)
            result = qbo_client.sync_invoices(conn, full_resync=full_resync)
        except qbo_client.QBOReauthRequired as e:
            raise HTTPException(409, f"reconnect required: {e}")
    return {"items": items, **result}
