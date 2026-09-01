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
import tempfile
import time

from ..reuse import REPO_ROOT
from ..errors import ApiProblem, NotFound
from . import audit, po_admin

_SCRIPT = os.path.join(REPO_ROOT, "run_cloud_extraction.py")
# How long the request waits on the child before returning "running". Kept well
# under Cloudflare's ~100s edge timeout so the caller always gets a real JSON
# response; the child is NOT killed and finishes (and writes the PO) on its own.
_SOFT_WAIT_S = 80
_POLL_S = 1.0

# Outcomes is_known() / errored_thread_ids() treat as settled — re-running the
# model won't move them, so the action is refused with a clear reason.
_SETTLED = {"not a purchase order"}


class RetryUnavailable(ApiProblem):
    """The pipeline can't run here (Gmail not connected, creds absent). 503."""

    status = 503
    code = "retry_unavailable"


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
    """Launch `run_cloud_extraction.py --thread <id>` and wait up to _SOFT_WAIT_S
    for it. If it finishes, parse its `RESULT_JSON:` line. If it doesn't, return
    `{"status": "running"}` and leave the child running detached — it writes the
    PO row on its own; the UI refetches to pick it up. So the request always
    returns real JSON (with CORS), never a proxy 504.

    The child's stdout+stderr go to a temp file, not a pipe: a pipe left unread
    after we return "running" would fill and then break on the API process's fd
    cleanup, killing the child mid-run."""
    fd, out_path = tempfile.mkstemp(prefix="retry_ext_", suffix=".out")
    proc = None
    try:
        with os.fdopen(fd, "w") as sink:
            proc = subprocess.Popen(
                [sys.executable, _SCRIPT, "--thread", thread_id,
                 "--log-file", "/tmp/retry_extraction.log"],
                stdout=sink, stderr=subprocess.STDOUT, text=True,
                env={**os.environ},
                start_new_session=True,  # detach from the request's process group
            )

        deadline = time.monotonic() + _SOFT_WAIT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(_POLL_S)
        else:
            return {"status": "running"}  # still going — don't kill it, don't clean up

        with open(out_path, encoding="utf-8", errors="replace") as fh:
            output = fh.read()
    finally:
        # only remove the file once the child is done with it
        if proc is None or proc.poll() is not None:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    line = next(
        (ln for ln in reversed(output.splitlines()) if ln.startswith("RESULT_JSON: ")),
        None,
    )
    if line is None:
        tail = output.strip()[-500:]
        raise ApiProblem(
            f"The extraction subprocess didn't return a result (exit {proc.returncode}). {tail}",
            code="retry_failed",
        )

    result = json.loads(line[len("RESULT_JSON: "):])
    if result.get("status") == "unavailable":
        raise RetryUnavailable(result.get("error") or "The extraction pipeline isn't available here.")
    return result
