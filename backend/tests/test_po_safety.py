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


# --- authorization tiers (no DB: app_role falls back to 'editor') -----------

import datetime as _dt  # noqa: E402

import jwt as _jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_client = TestClient(app)


def _tok() -> str:
    return _jwt.encode(
        {
            "sub": "u", "email": "nobody@example.com", "aud": "authenticated",
            "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1),
        },
        os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256",
    )


def test_me_defaults_to_editor_without_app_users():
    r = _client.get("/api/me", headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 200
    assert r.json() == {"email": "nobody@example.com", "role": "editor"}


def test_admin_route_forbidden_for_editor():
    r = _client.post(
        "/api/po/1/status",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {_tok()}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"
    assert r.json()["detail"]["need"] == "admin"


def test_connection_disconnect_forbidden_for_editor():
    # disconnecting a data source is admin-only (audit finding #1)
    r = _client.post(
        "/api/connections/qbo/disconnect",
        headers={"Authorization": f"Bearer {_tok()}"},
    )
    assert r.status_code == 403 and r.json()["detail"]["need"] == "admin"


def test_saved_view_delete_requires_kind():
    r = _client.request(
        "DELETE",
        "/api/settings/views",
        json={"name": "x"},  # missing kind
        headers={"Authorization": f"Bearer {_tok()}"},
    )
    assert r.status_code == 422


# --- reconcile line diff (pure) -------------------------------------------

from app.services.reconcile import line_diff  # noqa: E402


def _li(p, s, q, up, lt):
    return {"product_name": p, "container_size": s, "quantity": q, "unit_price": up, "line_total": lt}


def test_line_diff_clean_match():
    po = [_li("Arugula", "4oz", 10, 2.5, 25.0)]
    inv = [_li("arugula", "4 oz", 10, 2.5, 25.0)]  # normalisation collapses the key
    d = line_diff(po, inv)
    assert d["clean"] and d["n_diff"] == 0
    assert d["rows"][0]["status"] == "match"
    assert d["totals"] == {"po": 25.0, "inv": 25.0, "delta": 0.0}


def test_line_diff_qty_and_only_rows():
    po = [_li("Arugula", "4oz", 10, 2.5, 25.0), _li("Basil", "2oz", 4, 3.0, 12.0)]
    inv = [_li("Arugula", "4oz", 12, 2.5, 30.0), _li("Cilantro", "2oz", 1, 5.0, 5.0)]
    d = line_diff(po, inv)
    by = {(r["product"], r["status"]) for r in d["rows"]}
    assert ("Arugula", "total_diff") in by  # 25 -> 30
    assert ("Basil", "po_only") in by
    assert ("Cilantro", "inv_only") in by
    assert d["totals"]["delta"] == round(35.0 - 37.0, 2)


def test_editor_route_allowed_for_editor_reaches_service():
    # editor tier passes the role gate; the call then fails at the DB (no server)
    # -> 500, NOT 403. Proves require_editor isn't blocking an editor.
    r = _client.post(
        "/api/po/1",
        json={"header": {}, "items": [], "removed_items": []},
        headers={"Authorization": f"Bearer {_tok()}"},
    )
    assert r.status_code != 403


# --- doc upload guards (pre-DB, no server needed) -------------------------

import base64 as _b64  # noqa: E402


def _upload(content_b64: str):
    return _client.post(
        "/api/po/1/documents/upload",
        json={"filename": "x", "content_b64": content_b64},
        headers={"Authorization": f"Bearer {_tok()}"},
    )


def test_doc_upload_rejects_non_pdf_or_image():
    r = _upload(_b64.b64encode(b"just some text, not a document").decode())
    assert r.status_code == 415


def test_doc_upload_rejects_oversize():
    from app.routers.po_docs import MAX_UPLOAD_BYTES

    big = _b64.b64encode(b"%PDF-" + b"\x00" * (MAX_UPLOAD_BYTES + 10)).decode()
    r = _upload(big)
    assert r.status_code == 413


def test_doc_upload_empty():
    assert _upload("").status_code == 422


# --- math_check magnitude-scaled tolerance -------------------------------

from math_check import validate_math as _validate_math  # noqa: E402


def test_math_tolerance_scales_with_magnitude():
    # $3 off on a ~$50k order is < 0.1% -> not flagged
    big = {"subtotal": 50000.0, "tax": 0.0, "total": 50003.0, "line_items": []}
    _validate_math(big)
    assert not big["math_check_failed"]
    # $3 off on a $100 order IS flagged
    small = {"subtotal": 100.0, "tax": 0.0, "total": 103.0, "line_items": []}
    _validate_math(small)
    assert small["math_check_failed"]
