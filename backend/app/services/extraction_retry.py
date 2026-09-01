"""Per-PO "Retry extraction" — re-run the Gmail extraction pipeline for one PO
row that recorded a genuine failure (a transient API / credit / timeout error),
in-process, and report what happened. The heavy lifting lives in the reused
`run_cloud_extraction` module; this is the guard + audit wrapper.

The batch equivalent is `run_cloud_extraction.py --retry-errors` (extract_pos.yml's
`retry_errors` dispatch input) — same predicate, whole backlog at once.
"""

from __future__ import annotations

import run_cloud_extraction  # repo root, via app.reuse

from ..config import get_settings
from ..errors import ApiProblem, NotFound
from . import audit, po_admin

# Outcomes is_known() / errored_thread_ids() treat as settled — re-running the
# model won't move them, so the action is refused with a clear reason.
_SETTLED = {"not a purchase order"}


class RetryUnavailable(ApiProblem):
    """The pipeline can't run here (Gmail not connected, creds absent). 503."""

    status = 503
    code = "retry_unavailable"


def retry(conn, po_id: int, actor: str | None) -> dict:
    """Re-extract the Gmail thread behind `po_id` and republish it. Returns
    `{status, ...}` from run_cloud_extraction.retry_single_thread plus the
    refreshed PO detail under `po`. Raises ApiProblem on a bad request."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_file, gmail_thread_id, error, "
            "       COALESCE(status, 'active') AS status, COALESCE(edited, FALSE) AS edited "
            "FROM purchase_orders WHERE id = %s",
            (po_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise NotFound(f"PO {po_id} not found.")
    source_file, thread_id, error, status, edited = row

    if not error or error.strip() == "":
        raise ApiProblem("This PO didn't fail extraction — there's nothing to retry.",
                         code="not_retryable")
    if error in _SETTLED:
        raise ApiProblem(
            'The model classified this thread as "not a purchase order". '
            "Re-running won't change that — mark it a PO by hand if it is one.",
            code="not_retryable",
        )
    if error.startswith("modification"):
        raise ApiProblem(
            "This is an unresolved order modification — link it to the PO it "
            "revises on the reconcile screen; a re-run can't resolve the target.",
            code="not_retryable",
        )
    if status != "active":
        raise ApiProblem(f"This PO is {status}; reactivate it before retrying extraction.",
                         code="not_active")
    if edited:
        raise ApiProblem("This PO was hand-edited — retrying would overwrite your changes.",
                         code="po_edited")

    if not thread_id and (source_file or "").startswith("gmail-thread:"):
        thread_id = source_file.split(":", 1)[1]
    if not thread_id:
        raise ApiProblem(
            "Only Gmail-thread extractions can be retried from here. For a PDF "
            "source, use the extract_pos workflow (retry_errors).",
            code="not_a_thread",
        )

    try:
        result = run_cloud_extraction.retry_single_thread(
            get_settings().database_url, thread_id
        )
    except RuntimeError as exc:  # Gmail not connected / creds absent
        raise RetryUnavailable(str(exc)) from exc

    audit.log(
        conn, actor=actor, action="retry_extraction", entity="purchase_order",
        entity_id=po_id, before={"error": error}, after=result,
    )
    conn.commit()

    detail = po_admin.po_detail(conn, po_id)
    return {**result, "po": detail}
