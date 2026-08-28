"""Browser-facing OAuth callbacks. Google / Intuit redirect here after consent;
these carry NO bearer token. Each verifies the signed `state`, exchanges the
code, stores the tokens, then 302s the browser back to the SPA's Settings page."""

import gmail_client  # repo root, via app.reuse
import qbo_client  # dashboard/, via app.reuse
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import oauth_state
from ..config import get_settings
from ..reused_db import reused_conn

router = APIRouter(prefix="/auth", tags=["oauth"])


def _back(status: str) -> RedirectResponse:
    base = get_settings().frontend or "/"
    return RedirectResponse(f"{base}/settings?connect={status}", status_code=302)


@router.get("/qbo/callback")
def qbo_callback(request: Request) -> RedirectResponse:
    qp = request.query_params
    code, realm_id, state = qp.get("code"), qp.get("realmId"), qp.get("state", "")
    if not code or not realm_id:
        return _back("qbo_error")
    if not oauth_state.verify(state, "qbo"):
        return _back("qbo_state_mismatch")
    try:
        with reused_conn() as conn:
            qbo_client.exchange_code_for_tokens(conn, code, realm_id)
    except Exception:
        return _back("qbo_error")
    return _back("qbo_ok")


@router.get("/gmail/callback")
def gmail_callback(request: Request) -> RedirectResponse:
    qp = request.query_params
    code, state = qp.get("code"), qp.get("state", "")
    if not code:
        return _back("gmail_error")
    if not oauth_state.verify(state, "gmail"):
        return _back("gmail_state_mismatch")
    s = get_settings()
    try:
        with reused_conn() as conn:
            gmail_client.exchange_code_for_tokens(
                conn, s.gmail_client_id, s.gmail_client_secret, s.gmail_redirect_uri, code
            )
    except Exception:
        return _back("gmail_error")
    return _back("gmail_ok")
