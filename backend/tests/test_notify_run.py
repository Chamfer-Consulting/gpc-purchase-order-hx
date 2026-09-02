"""notify_run.py — the Slack text + audit-row builders and the summary-file
fallback. No Slack, no DB (both side effects are guarded by env vars)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401 — puts the repo root on sys.path
import notify_run  # noqa: E402


def test_slack_text_ok_has_check_stats_and_run_link():
    s = {"kind": "qbo_sync", "status": "ok",
         "stats": {"items": 12, "invoices_synced": 40, "invoices_pruned": 2}}
    t = notify_run.slack_text(s, "http://run/1")
    assert t.startswith("✅ *QuickBooks sync* — ok")
    assert "40 invoices" in t and "12 catalog items" in t and "2 pruned" in t
    assert "<http://run/1|GitHub run log>" in t


def test_slack_text_partial_extraction_digest():
    s = {"kind": "extraction", "status": "partial",
         "stats": {"extracted": 30, "errors": 3, "skipped": 1, "cursor_advanced": False}}
    t = notify_run.slack_text(s, None)
    assert t.startswith("⚠️ *PO extraction* — partial")
    assert "30 extracted" in t and "3 error(s)" in t and "1 skipped" in t and "cursor held" in t
    assert "GitHub run log" not in t  # no url passed


def test_slack_text_reauth_tells_you_to_reconnect():
    t = notify_run.slack_text({"kind": "qbo_sync", "status": "reauth_required"}, "http://r")
    assert t.startswith("⏸️ *QuickBooks sync* — reauth required")
    assert "reconnect" in t.lower()


def test_slack_text_failed_shows_error():
    t = notify_run.slack_text(
        {"kind": "doc_capture", "status": "failed", "error": "OperationalError: boom"}, "http://r"
    )
    assert t.startswith("❌ *Document capture* — failed")
    assert "OperationalError: boom" in t


def test_audit_after_surfaces_error_as_reason():
    a = notify_run.audit_after(
        {"status": "failed", "error": "boom", "stats": {"published": 0}}, "http://r"
    )
    assert a["status"] == "failed"
    assert a["error"] == "boom" and a["reason"] == "boom"  # derive_reason reads `reason`
    assert a["published"] == 0 and a["run_url"] == "http://r"


def test_audit_after_reauth_reason_without_error():
    a = notify_run.audit_after({"status": "reauth_required", "stats": {}}, None)
    assert a["reason"] == "QuickBooks needs reconnecting"


def test_build_summary_falls_back_to_crashed_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notify_run.pipeline_summary, "SUMMARY_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("JOB_STATUS", "failure")
    s = notify_run.build_summary("extraction")
    assert s == {"kind": "extraction", "status": "crashed", "error": None, "stats": {}}


def test_build_summary_uses_matching_file(tmp_path, monkeypatch):
    p = tmp_path / "run-summary.json"
    monkeypatch.setattr(notify_run.pipeline_summary, "SUMMARY_PATH", str(p))
    notify_run.pipeline_summary.write("qbo_sync", "ok", items=1)
    s = notify_run.build_summary("qbo_sync")
    assert s["kind"] == "qbo_sync" and s["status"] == "ok" and s["stats"]["items"] == 1
    # a summary written by a different script is ignored -> fallback
    monkeypatch.setenv("JOB_STATUS", "success")
    assert notify_run.build_summary("extraction")["status"] == "ok"
