"""Per-PO "Retry extraction" — re-run the Gmail extraction pipeline for one PO
row that recorded a genuine failure (a transient API / credit / timeout error).

The extraction runs in a **short-lived subprocess** (`run_cloud_extraction.py
--thread <id>`), not in-process: it isolates the pipeline's heavy import graph
(pdfplumber, pandas, …) and a possibly-slow Claude call from the API worker, so a
retry can't block the event loop or OOM the container. Same DB, same env.

The batch equivalent is `run_cloud_extraction.py --retry-errors` (extract_pos.yml's
`retry_errors` dispatch input) — same predicate, whole backlog at once.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from ..reuse import REPO_ROOT
from ..errors import ApiProblem, NotFound
from . import audit, po_admin

_SCRIPT = os.path.join(REPO_ROOT, "run_cloud_extraction.py")
_TIMEOUT_S = 110  # under Cloudflare's ~100s edge timeout is ideal; give a little slack

# Outcomes is_known() / errored_thread_ids() treat as settled — re-running the
# model won't move them, so the action is refused with a clear reason.
_SETTLED = {"not a purchase order"}


class RetryUnavailable(ApiProblem):
    """The pipeline can't run here (Gmail not connected, creds absent). 503."""

    status = 503
    code = "retry_unavailable"


class RetryTimeout(ApiProblem):
    """The extraction didn't finish inside the request budget. 504 — it may still
    land; the batch `--retry-errors` workflow is the fallback."""

    status = 504
    code = "retry_timeout"


def retry(conn, po_id: int, actor: str | None) -> dict:
    """Re-extract the Gmail thread behind `po_id` and republish it. Returns
    `{status, ...}` from run_cloud_extraction plus the refreshed PO detail under
    `po`. Raises a typed ApiProblem on a bad request / unavailable pipeline."""
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

    result = _run_subprocess(thread_id)

    audit.log(
        conn, actor=actor, action="retry_extraction", entity="purchase_order",
        entity_id=po_id, before={"error": error}, after=result,
    )
    conn.commit()

    detail = po_admin.po_detail(conn, po_id)
    return {**result, "po": detail}


def _run_subprocess(thread_id: str) -> dict:
    """`run_cloud_extraction.py --thread <id>` in a child process, parsed back from
    its `RESULT_JSON:` line."""
    try:
        proc = subprocess.run(
            [sys.executable, _SCRIPT, "--thread", thread_id, "--log-file", "/tmp/retry_extraction.log"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired as exc:
        raise RetryTimeout(
            "The re-extraction is taking too long — it may still finish in the "
            "background. Reload in a minute, or run the retry_errors workflow."
        ) from exc

    line = next(
        (ln for ln in reversed((proc.stdout or "").splitlines()) if ln.startswith("RESULT_JSON: ")),
        None,
    )
    if line is None:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise ApiProblem(
            f"The extraction subprocess didn't return a result (exit {proc.returncode}). {tail}",
            code="retry_failed",
        )

    result = json.loads(line[len("RESULT_JSON: "):])
    if result.get("status") == "unavailable":
        raise RetryUnavailable(result.get("error") or "The extraction pipeline isn't available here.")
    return result
