"""Who am I + what can I do. The SPA reads /me once to gate edit/admin controls,
and pings /activity on sign-in / sign-out so the audit trail has a login history."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..auth import AuthedUser, app_role, current_user
from ..reused_db import reused_conn
from ..services import audit

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: AuthedUser = Depends(current_user)) -> dict:
    return {"email": user.email, "role": app_role(user.email)}


class ActivityIn(BaseModel):
    event: Literal["login", "logout"]


@router.post("/activity")
def record_activity(
    body: ActivityIn, request: Request, user: AuthedUser = Depends(current_user)
) -> dict:
    """Record a sign-in / sign-out in the audit trail. Best-effort and idempotent
    per browser session (see audit.record_auth_event) — the client fires it more
    than once."""
    actor = (user.email or user.id or "").lower()
    with reused_conn() as conn:
        wrote = audit.record_auth_event(
            conn,
            email=actor,
            event=body.event,
            session_id=user.session_id,
            user_agent=request.headers.get("user-agent"),
        )
        conn.commit()
    return {"ok": True, "recorded": wrote}
