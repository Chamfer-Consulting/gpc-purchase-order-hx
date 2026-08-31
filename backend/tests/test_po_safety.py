"""Safety-foundation unit tests (no DB): the lifecycle state machine and the typed
error bodies. DB-backed behaviour (optimistic concurrency 409, line-diff save,
atomic bulk) is exercised by the manual verification in the plan — CI has no
Postgres service."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

import app.reuse  # noqa: E402,F401 — sys.path shim for the reused repo modules

# --- lifecycle state machine ------------------------------------------------

from app.errors import BadTransition, BulkTransitionError, NotActive, StaleWrite  # noqa: E402
from app.services.po_admin import ALLOWED_TRANSITIONS, _check_transition  # noqa: E402


@pytest.mark.parametrize(
    "src,dst",
    [
        ("active", "cancelled"),
        ("active", "deleted"),
        ("cancelled", "active"),
        ("deleted", "active"),
        ("draft", "deleted"),
        ("withdrawn", "active"),
        ("active", "active"),  # reason-only edit, same status
    ],
)
def test_allowed_transitions_pass(src, dst):
    _check_transition(src, dst)  # no raise


@pytest.mark.parametrize(
    "src,dst",
    [
        ("cancelled", "withdrawn"),
        ("deleted", "cancelled"),
        ("voided", "withdrawn"),
        ("draft", "cancelled"),
    ],
)
def test_disallowed_transitions_raise(src, dst):
    with pytest.raises(BadTransition) as ei:
        _check_transition(src, dst)
    body = ei.value.body()
    assert body["code"] == "bad_transition"
    assert body["from_status"] == src and body["to_status"] == dst
    assert isinstance(body["allowed"], list)


def test_every_status_has_a_transition_entry():
    from app.services.po_admin import VALID_STATUS

    assert set(ALLOWED_TRANSITIONS) == set(VALID_STATUS)


# --- typed error bodies ---------------------------------------------------


def test_stale_write_body():
    e = StaleWrite(current_version=7, edited_by="a@b.com", edited_at="2026-09-01T10:00:00")
    b = e.body()
    assert b["code"] == "stale_write" and e.status == 409
    assert b["current_version"] == 7 and b["edited_by"] == "a@b.com"


def test_not_active_body():
    e = NotActive("cancelled")
    assert e.status == 409 and e.body()["code"] == "not_active"
    assert e.body()["status"] == "cancelled"


def test_bulk_transition_body():
    e = BulkTransitionError(missing=[9], invalid=[{"po_id": 3, "from_status": "deleted", "to_status": "withdrawn"}])
    b = e.body()
    assert e.status == 422 and b["code"] == "bulk_bad_transition"
    assert b["missing"] == [9] and len(b["invalid"]) == 1
