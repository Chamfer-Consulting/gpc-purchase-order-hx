"""Audit history — the cross-system activity feed for the admin `/audit` page.
Read-only, admin-only. The feed unions admin mutations (audit_log) with
extraction-review decisions; connection connect/disconnect/sync events are logged
straight into audit_log. See services/audit.py:timeline()."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from ..auth import AuthedUser, require_admin
from ..reused_db import reused_conn
from ..services import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(
    actor: str | None = None,
    source: str | None = None,
    action: str | None = None,
    entity: str | None = None,
    q: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthedUser = Depends(require_admin),
) -> dict:
    # `until` is an inclusive calendar day from the UI — bump it to the exclusive
    # start of the next day so the whole day is covered.
    until_excl = (until + timedelta(days=1)) if until else None
    with reused_conn() as conn:
        return audit.timeline(
            conn,
            actor=actor,
            source=source,
            action=action,
            entity=entity,
            q=q,
            since=since,
            until=until_excl,
            limit=limit,
            offset=offset,
        )


@router.get("/options")
def audit_options(_: AuthedUser = Depends(require_admin)) -> dict:
    with reused_conn() as conn:
        return audit.facets(conn)
