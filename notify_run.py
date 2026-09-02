"""Final step of every scheduled workflow: take the run outcome — from
pipeline_summary's run-summary.json, or the GitHub job status if the run crashed
before writing one — and

  * post it to Slack   (SLACK_WEBHOOK_URL, optional)
  * record one row on the in-app audit timeline  (audit_log, via DATABASE_URL)

so a run's success / partial-failure / "reconnect QuickBooks" is visible without
opening the Actions tab. Always exits 0: a notifier must never turn a green run
red, nor a red run into a confusing double failure.

    python notify_run.py --kind extraction|doc_capture|qbo_sync
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import pipeline_summary

log = logging.getLogger("notify_run")

_TITLES = {
    "extraction": "PO extraction",
    "doc_capture": "Document capture",
    "qbo_sync": "QuickBooks sync",
}
_EMOJI = {
    "ok": "✅",              # ✅
    "partial": "⚠️",   # ⚠️
    "stopped": "⚠️",
    "paused": "⏸️",    # ⏸️
    "reauth_required": "⏸️",
    "failed": "❌",          # ❌
    "crashed": "❌",
}


def _digest(kind: str, stats: dict) -> str:
    """One human line of the run's numbers ('' when there are none — e.g. a crash
    before the script could report)."""
    s = stats or {}
    if not s:
        return ""
    if kind == "extraction":
        parts = [f"{int(s.get('extracted', 0))} extracted"]
        if s.get("errors"):
            parts.append(f"{int(s['errors'])} error(s)")
        if s.get("skipped"):
            parts.append(f"{int(s['skipped'])} skipped")
        parts.append("cursor advanced" if s.get("cursor_advanced") else "cursor held")
        return " · ".join(parts)
    if kind == "doc_capture":
        parts = []
        for k in ("gmail", "qbo"):
            r = s.get(k)
            if isinstance(r, dict):
                parts.append(
                    f"{k}: {int(r.get('captured', 0))} captured / {int(r.get('scanned', 0))} scanned"
                )
        if s.get("failed"):
            parts.append(f"{int(s['failed'])} failed")
        return " · ".join(parts) or "nothing to capture"
    if kind == "qbo_sync":
        parts = [
            f"{int(s.get('invoices_synced', 0))} invoices",
            f"{int(s.get('items', 0))} catalog items",
        ]
        if s.get("invoices_pruned"):
            parts.append(f"{int(s['invoices_pruned'])} pruned")
        if s.get("matching"):
            parts.append(f"matching: {s['matching']}")
        return " · ".join(parts)
    return ", ".join(f"{k}={v}" for k, v in s.items())


def slack_text(summary: dict, run_url: str | None) -> str:
    kind = summary.get("kind", "pipeline")
    status = summary.get("status", "crashed")
    title = _TITLES.get(kind, kind)
    emoji = _EMOJI.get(status, "•")
    lines = [f"{emoji} *{title}* — {status.replace('_', ' ')}"]
    if status in ("failed", "crashed") and summary.get("error"):
        lines.append(f"> {summary['error']}")
    elif status == "reauth_required":
        lines.append("> QuickBooks needs reconnecting — Settings → QuickBooks in the dashboard.")
    lines.append(_digest(kind, summary.get("stats") or {}))
    if run_url:
        lines.append(f"<{run_url}|GitHub run log>")
    return "\n".join(p for p in lines if p)


def slack_payload(summary: dict, run_url: str | None) -> dict:
    return {"text": slack_text(summary, run_url)}


def audit_after(summary: dict, run_url: str | None) -> dict:
    """The JSON stored on the audit_log row. `reason` is what /audit shows in its
    'Why' column (services/audit.py:derive_reason reads that key)."""
    out: dict = {"status": summary.get("status"), "run_url": run_url}
    out.update(summary.get("stats") or {})
    if summary.get("error"):
        out["error"] = summary["error"]
        out["reason"] = summary["error"]
    elif summary.get("status") == "reauth_required":
        out["reason"] = "QuickBooks needs reconnecting"
    return out


def build_summary(kind: str) -> dict:
    """The run's summary file, or a status-only fallback when the run crashed
    before writing one (or the file on disk is a stale one from another script)."""
    s = pipeline_summary.read()
    if s and s.get("kind") == kind:
        return s
    job = (os.environ.get("JOB_STATUS") or "").lower()
    return {
        "kind": kind,
        "status": "ok" if job == "success" else "crashed",
        "error": None,
        "stats": {},
    }


def _post_slack(payload: dict) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        log.info("SLACK_WEBHOOK_URL not set — skipping Slack. Would have sent:\n%s", payload["text"])
        return
    try:
        import requests

        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log.warning("Slack webhook returned %s: %s", r.status_code, r.text[:200])
        else:
            log.info("Slack notified.")
    except Exception as exc:  # network, DNS, bad URL — never fatal
        log.warning("Slack post failed — %s", exc)


def _write_audit(kind: str, summary: dict, run_url: str | None) -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        log.info("DATABASE_URL not set — skipping the audit-log row")
        return
    try:
        import psycopg2

        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (actor, action, entity, entity_id, before, after) "
                    "VALUES (%s, %s, %s, %s, NULL, %s)",
                    (
                        "scheduler",
                        "run",
                        "pipeline",
                        kind,
                        json.dumps(audit_after(summary, run_url), default=str),
                    ),
                )
            conn.commit()
            log.info("audit_log row written (pipeline/run/%s).", kind)
        finally:
            conn.close()
    except Exception as exc:  # DB down / table missing — never fatal
        log.warning("could not write the audit-log row — %s", exc)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Post a scheduled run's outcome to Slack + the audit log")
    ap.add_argument("--kind", required=True, choices=sorted(_TITLES))
    args = ap.parse_args(argv)

    run_url = os.environ.get("GITHUB_RUN_URL") or None
    summary = build_summary(args.kind)
    log.info("run outcome: %s / %s", summary.get("kind"), summary.get("status"))

    _post_slack(slack_payload(summary, run_url))
    _write_audit(args.kind, summary, run_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
