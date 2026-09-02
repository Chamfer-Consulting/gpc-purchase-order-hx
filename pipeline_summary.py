"""One tiny job: the scheduled scripts (run_cloud_extraction / run_doc_capture /
run_qbo_sync) drop their run outcome here on every handled exit path, and the
workflow's final `notify_run.py` step picks it up to post to Slack + the in-app
audit timeline. Best-effort — a failure to write the summary must never disturb
the run itself.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SUMMARY_PATH = os.environ.get("PIPELINE_SUMMARY_PATH", "run-summary.json")

# kind: extraction | doc_capture | qbo_sync
# status: ok | partial | paused | stopped | reauth_required | failed
_STATUSES = {"ok", "partial", "paused", "stopped", "reauth_required", "failed"}


def write(kind: str, status: str, *, error: str | None = None, **stats) -> None:
    """Overwrite run-summary.json with this run's outcome. Never raises."""
    if status not in _STATUSES:  # a typo shouldn't lose the notification
        log.warning("pipeline_summary: unknown status %r for %s", status, kind)
    payload = {
        "kind": kind,
        "status": status,
        "error": (str(error)[:2000] if error else None),
        "stats": stats,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str)
    except Exception as exc:  # disk full, read-only fs, …
        log.warning("pipeline_summary: could not write %s — %s", SUMMARY_PATH, exc)


def read() -> dict | None:
    try:
        with open(SUMMARY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("pipeline_summary: could not read %s — %s", SUMMARY_PATH, exc)
        return None
