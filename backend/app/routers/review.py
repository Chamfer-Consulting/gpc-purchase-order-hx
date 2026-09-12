"""Extraction review — the training loop's UI backend. Decision CRUD goes straight
through extraction_reviews.py (reused); the queue + revision candidates are in
services/review_queue.py."""

import extraction_reviews  # repo root, via app.reuse
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from ..auth import AuthedUser, current_user, require_editor
from ..reused_db import reused_conn
from ..services import audit, review_queue

router = APIRouter(prefix="/api/review", tags=["review"])


class Decision(BaseModel):
    target_kind: str  # "thread" | "file"
    target_key: str
    verdict: str  # "is_po" | "not_po" | "needs_fix"
    revision_of: str | None = None
    standalone: bool = False
    corrected: dict | None = None
    note: str | None = None


@router.get("/queue")
def queue(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return {"items": review_queue.review_queue(conn)}


@router.get("/candidates")
def candidates(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        return {"items": review_queue.revision_candidates(conn)}


@router.get("/decisions")
def decisions(_: AuthedUser = Depends(current_user)) -> dict:
    with reused_conn() as conn:
        rows = extraction_reviews.all_decisions(conn)
    for r in rows:  # jsonify datetimes
        for k in ("decided_at", "updated_at"):
            if r.get(k) is not None and hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
    return {"items": rows}


@router.post("/decision")
def upsert(d: Decision, user: AuthedUser = Depends(require_editor)) -> dict:
    with reused_conn() as conn:
        # snapshot the content the decision is being made on, so the eval can replay it
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, content_hash FROM extraction_snapshots "
                "WHERE target_kind = %s AND target_key = %s",
                (d.target_kind, d.target_key),
            )
            snap = cur.fetchone()

        extraction_reviews.upsert_decision(
            conn,
            target_kind=d.target_kind,
            target_key=d.target_key,
            verdict=d.verdict,
            content_hash=snap[1] if snap else None,
            content_snapshot=snap[0] if snap else None,
            revision_of=d.revision_of,
            standalone=d.standalone,
            corrected=d.corrected,
            reviewer=user.email or "dashboard",
            note=d.note,
            commit=False,  # one transaction with the purchase_orders reconcile below
        )

        # Reconcile stored purchase_orders rows so the rest of the app agrees now.
        with conn.cursor() as cur:
            if d.target_kind == "thread":
                where, params = "(gmail_thread_id = %s OR source_file = %s)", (
                    d.target_key,
                    f"gmail-thread:{d.target_key}",
                )
            else:
                where, params = "source_file = %s", (d.target_key,)
            if d.verdict == "not_po":
                cur.execute(
                    f"UPDATE purchase_orders SET error = 'not a purchase order' "
                    f"WHERE {where} AND (error IS NULL OR error = '')",
                    params,
                )
            elif d.verdict == "is_po":
                cur.execute(
                    f"UPDATE purchase_orders SET error = NULL "
                    f"WHERE {where} AND error = 'not a purchase order'",
                    params,
                )
        conn.commit()
    return {"ok": True}


@router.delete("/decision")
def remove(
    target_kind: str = Body(...), target_key: str = Body(...),
    user: AuthedUser = Depends(require_editor),
) -> dict:
    with reused_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT verdict, revision_of, standalone, reviewer FROM extraction_reviews "
                "WHERE target_kind = %s AND target_key = %s",
                (target_kind, target_key),
            )
            row = cur.fetchone()
        if row is None:
            return {"ok": True, "retracted": False}  # nothing to undo
        extraction_reviews.delete_decision(conn, target_kind, target_key, commit=False)
        audit.log(
            conn, actor=user.email, action="verdict_retracted",
            entity="extraction_review", entity_id=target_key,
            before={
                "verdict": row[0], "revision_of": row[1],
                "standalone": row[2], "reviewer": row[3],
            },
        )
        conn.commit()
    return {"ok": True, "retracted": True}
