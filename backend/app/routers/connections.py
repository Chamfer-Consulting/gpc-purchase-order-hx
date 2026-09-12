"""Gmail + QuickBooks connection status / connect / disconnect. The OAuth
*callbacks* (browser redirects from Google / Intuit) are in routers/oauth.py and
carry no bearer token; everything here requires one."""

import gmail_client  # repo root, via app.reuse
import qbo_client  # shared/, via app.reuse
from fastapi import APIRouter, Depends, HTTPException

from .. import oauth_state
from ..auth import AuthedUser, current_user, require_admin, require_editor
from ..cache import clear as clear_cache
from ..config import get_settings
from ..reused_db import reused_conn
from ..services import audit


def _actor(user: AuthedUser) -> str | None:
    return user.email or user.id

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
def gmail_authorize(user: AuthedUser = Depends(require_admin)) -> dict:
    s = get_settings()
    if not (s.gmail_client_id and s.gmail_redirect_uri):
        raise HTTPException(503, "Gmail OAuth is not configured (GMAIL_CLIENT_ID / GMAIL_REDIRECT_URI).")
    st = oauth_state.issue("gmail", actor=_actor(user))
    return {"url": gmail_client.build_authorize_url(s.gmail_client_id, s.gmail_redirect_uri, st)}


@router.get("/qbo/authorize")
def qbo_authorize(user: AuthedUser = Depends(require_admin)) -> dict:
    st = oauth_state.issue("qbo", actor=_actor(user))
    try:
        return {"url": qbo_client.build_authorize_url(st)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.post("/gmail/disconnect")
def gmail_disconnect(user: AuthedUser = Depends(require_admin)) -> dict:
    with reused_conn() as conn:
        gmail_client.disconnect(conn)
        audit.log(conn, actor=_actor(user), action="disconnect",
                  entity="connection", entity_id="gmail")
        conn.commit()
    return {"ok": True}


@router.post("/qbo/disconnect")
def qbo_disconnect(user: AuthedUser = Depends(require_admin)) -> dict:
    with reused_conn() as conn:
        qbo_client.disconnect(conn)
        audit.log(conn, actor=_actor(user), action="disconnect",
                  entity="connection", entity_id="qbo")
        conn.commit()
    return {"ok": True}


@router.post("/qbo/sync")
def qbo_sync(full_resync: bool = False, user: AuthedUser = Depends(require_editor)) -> dict:
    """On-demand QuickBooks sync. The daily job (run_qbo_sync.py) is the norm; this
    is the 'sync now' button."""
    with reused_conn() as conn:
        try:
            items = qbo_client.sync_items(conn)
            result = qbo_client.sync_invoices(conn, full_resync=full_resync)
        except qbo_client.QBOReauthRequired as e:
            raise HTTPException(409, f"reconnect required: {e}")
        audit.log(conn, actor=_actor(user), action="sync", entity="connection",
                  entity_id="qbo",
                  after={"items": items, "full_resync": full_resync, **result})
        conn.commit()
    # the analytics pages (@cached by filter params) are all invoice-derived —
    # rebuild them so a "sync now" is visible immediately, not after the 5-min TTL.
    clear_cache()
    return {"items": items, **result}
