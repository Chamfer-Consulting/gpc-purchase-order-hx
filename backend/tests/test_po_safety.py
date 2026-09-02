"""Safety-foundation unit tests (no DB): the lifecycle state machine and the typed
error bodies. DB-backed behaviour (optimistic concurrency 409, line-diff save,
atomic bulk) is exercised by the manual verification in the plan — CI has no
Postgres service."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("ALLOWED_EMAIL_DOMAINS", "example.com")  # test tokens use @example.com

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


# --- authorization tiers ---------------------------------------------------
# No DB in these tests, so _app_user_role() can't read app_users. Fake it: the
# test user is an 'editor', an unknown allowed-domain user falls back to 'viewer'.

import datetime as _dt  # noqa: E402

import jwt as _jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.auth as _auth  # noqa: E402

_FAKE_ROLES = {"nobody@example.com": "editor"}
_auth._app_user_role = lambda e: _FAKE_ROLES.get((e or "").lower(), "")  # type: ignore[assignment]

from app.main import app  # noqa: E402

_client = TestClient(app)
# same app, but a 500 comes back as a response instead of re-raising the
# underlying exception into the test (used where a handler hits the absent DB).
_client_noraise = TestClient(app, raise_server_exceptions=False)


def _tok() -> str:
    return _jwt.encode(
        {
            "sub": "u", "email": "nobody@example.com", "aud": "authenticated",
            "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1),
        },
        os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256",
    )


def _tok_for(email: str) -> str:
    return _jwt.encode(
        {"sub": "u", "email": email, "aud": "authenticated",
         "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)},
        os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256",
    )


def test_me_reflects_the_app_users_role():
    r = _client.get("/api/me", headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 200
    assert r.json() == {"email": "nobody@example.com", "role": "editor"}


def test_me_defaults_to_viewer_for_an_allowed_user_with_no_row():
    r = _client.get("/api/me", headers={"Authorization": f"Bearer {_tok_for('stranger@example.com')}"})
    assert r.status_code == 200
    assert r.json() == {"email": "stranger@example.com", "role": "viewer"}


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


def test_reference_price_write_forbidden_for_editor():
    # a reference price changes what every future extraction flags — admin-only
    r = _client.post(
        "/api/pricing",
        json={"rows": [], "delete": []},
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


def test_ghost_invoice_ids():
    import pandas as pd

    from app.services.context import ghost_invoice_ids

    items = pd.DataFrame(
        [
            {"invoice_id": 1, "category": "product", "product_name": "Arugula"},
            {"invoice_id": 1, "category": "product", "product_name": "Basil"},    # mixed -> kept
            {"invoice_id": 2, "category": "product", "product_name": "Arugula"},  # all hidden -> ghost
            {"invoice_id": 3, "category": "delivery", "product_name": None},      # no product lines -> not ghost
            {"invoice_id": 4, "category": "product", "product_name": "Cilantro"}, # visible -> kept
        ]
    )
    assert ghost_invoice_ids(items, {"Arugula"}) == {2}
    assert ghost_invoice_ids(items, set()) == set()
    assert ghost_invoice_ids(items, {"Arugula", "Basil"}) == {1, 2}


def test_line_diff_qty_and_only_rows():
    po = [_li("Arugula", "4oz", 10, 2.5, 25.0), _li("Basil", "2oz", 4, 3.0, 12.0)]
    inv = [_li("Arugula", "4oz", 12, 2.5, 30.0), _li("Cilantro", "2oz", 1, 5.0, 5.0)]
    d = line_diff(po, inv)
    by = {(r["product"], r["status"]) for r in d["rows"]}
    assert ("Arugula", "total_diff") in by  # 25 -> 30
    assert ("Basil", "po_only") in by
    assert ("Cilantro", "inv_only") in by
    assert d["totals"]["delta"] == round(35.0 - 37.0, 2)


def test_line_diff_folds_po_freight_against_invoice_delivery():
    # PO carries $8 freight inside the product line's printed total; QBO books
    # delivery as its own line. Net product figures match and the freight
    # reconciles in the charges row, so the whole diff is clean.
    po = [{**_li("Arugula", "4oz", 10, 2.5, 33.0), "additional_cost": 8.0}]
    inv = [
        _li("Arugula", "4oz", 10, 2.5, 25.0),
        {**_li("Delivery", None, None, None, 8.0), "category": "delivery"},
        {**_li("Sample Kale", "2oz", 1, 0.0, 0.0), "category": "sample", "is_sample": True},
    ]
    d = line_diff(po, inv)
    assert d["clean"] and d["n_diff"] == 0
    prod = next(r for r in d["rows"] if r["product"] == "Arugula")
    assert prod["status"] == "match" and prod["po"]["line_total"] == 25.0
    charge = next(r for r in d["rows"] if r["is_charges"])
    assert charge["po"]["line_total"] == 8.0 and charge["inv"]["line_total"] == 8.0
    assert charge["status"] == "match"
    assert not any(r["product"] == "Sample Kale" for r in d["rows"])  # samples dropped
    assert d["totals"] == {"po": 33.0, "inv": 33.0, "delta": 0.0}


def test_line_diff_flags_freight_mismatch():
    # No PO freight, but the invoice tacks on a $12.50 delivery line.
    po = [_li("Arugula", "4oz", 10, 2.5, 25.0)]
    inv = [
        _li("Arugula", "4oz", 10, 2.5, 25.0),
        {**_li("Mileage", None, None, None, 12.5), "category": "delivery"},
    ]
    d = line_diff(po, inv)
    charge = next(r for r in d["rows"] if r["is_charges"])
    assert charge["status"] == "total_diff" and not d["clean"]
    assert d["totals"]["delta"] == 12.5


def test_editor_route_allowed_for_editor_reaches_service():
    # editor tier passes the role gate; the call then fails at the DB (no server)
    # -> 500, NOT 403. Proves require_editor isn't blocking an editor.
    r = _client_noraise.post(
        "/api/po/1",
        json={"header": {}, "items": [], "removed_items": []},
        headers={"Authorization": f"Bearer {_tok()}"},
    )
    assert r.status_code == 500  # reached the handler, DB absent — not a 403


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


def test_validate_math_clears_a_stale_line_flag():
    # a line whose arithmetic now checks out but carries an old mismatch string
    data = {
        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "line_items": [
            {"quantity": 10, "unit_price": 10.0, "line_total": 100.0,
             "math_mismatch": "10 x $9 = $90, not $100"},  # stale
        ],
    }
    _validate_math(data)
    assert data["line_items"][0]["math_mismatch"] is None
    assert not data["math_check_failed"]


def test_validate_math_flags_a_real_line_mismatch():
    data = {
        "subtotal": None, "tax": None, "total": None,
        "line_items": [{"quantity": 10, "unit_price": 10.0, "line_total": 250.0}],
    }
    _validate_math(data)
    assert data["line_items"][0]["math_mismatch"]  # "10 x $10.0 = $100.00, not $250.0"


# --- PO revision recency ordering ---------------------------------------

from qbo_matcher import po_recency as _po_recency  # noqa: E402


def test_po_recency_prefers_printed_then_received_then_sent():
    older_but_has_sent = {"sent_date": "2025-06-26", "po_date": "2025-06-25"}
    newer_printed = {"document_printed_at": "06/28/25 11:35a", "po_date": "2025-06-25"}
    newer_received = {"source_received_at": "2025-06-27 01:12:04", "po_date": "2025-06-25"}
    assert _po_recency(newer_printed) > _po_recency(older_but_has_sent)
    assert _po_recency(newer_received) > _po_recency(older_but_has_sent)
    assert _po_recency({}).year == 1  # datetime.min -> everything beats an undated row


# --- chart tooltip breakdowns (services/breakdown.py) ----------------------

import pandas as pd  # noqa: E402

from app.services import breakdown as _bd  # noqa: E402


def _mini_frame():
    return pd.DataFrame(
        {
            "effective_date": pd.to_datetime(
                ["2026-01-05", "2026-02-03", "2026-02-15", "2026-02-20"]
            ),
            "customer_name": ["OnlyCust", "A", "B", "A"],
            "product_name": ["OnlyProd", "X", "Y", "X"],
            "line_total": [999.0, 100.0, 50.0, 25.0],
            "id": [1, 2, 3, 4],
        }
    )


def test_by_month_handles_a_single_group_bucket():
    # 2026-01 has exactly one product — the MultiIndex `.loc` used to collapse to a
    # scalar here and 500 the whole page.
    b = _bd.by_month(
        _mini_frame(), ["2026-01", "2026-02", "2026-03"],
        group="product_name", value="line_total", label="Top products",
    )
    rows = {p.x: [(r.name, r.value) for r in p.rows] for p in b.points}
    assert rows["2026-01"] == [("OnlyProd", 999.0)]
    assert rows["2026-02"] == [("X", 125.0), ("Y", 50.0)]
    assert rows["2026-03"] == []


def test_by_category_handles_a_single_group_bar():
    b = _bd.by_category(
        _mini_frame(), ["X", "OnlyProd"],
        key="product_name", group="customer_name", value="line_total", label="Top customers",
    )
    rows = {p.x: [(r.name, r.value) for r in p.rows] for p in b.points}
    assert rows["OnlyProd"] == [("OnlyCust", 999.0)]
    assert rows["X"] == [("A", 125.0)]


def test_breakdown_on_empty_frame_is_empty_points():
    b = _bd.by_month(pd.DataFrame(), ["2026-01"], group="product_name",
                     value="line_total", label="x")
    assert [p.rows for p in b.points] == [[]]


# --- price-anomaly fuzzy customer fallback (price_check.py) ----------------

from price_check import (  # noqa: E402
    canonical_customer_map,
    flag_price_anomaly,
    same_customer,
)


def test_flag_price_anomaly_matches_a_drifted_customer_spelling():
    refs = {("Testa Produce", "Cilantro", "4oz"): 12.0}
    hot = {"unit_price": "15.00", "product_name": "Cilantro", "container_size": "4oz"}
    flag_price_anomaly(hot, "Steve Testa", refs)  # no exact key — fuzzy fallback
    assert hot["price_anomaly"] and "25%" in hot["price_anomaly"]

    ok = {"unit_price": "12.30", "product_name": "Cilantro", "container_size": "4oz"}
    flag_price_anomaly(ok, "Steve Testa Produce, LLC.", refs)
    assert "price_anomaly" not in ok  # within tolerance, drifted name


def test_flag_price_anomaly_still_silent_with_no_reference():
    hot = {"unit_price": "99.0", "product_name": "Nope", "container_size": "9oz"}
    flag_price_anomaly(hot, "Whoever", {("A", "B", "C"): 1.0})
    assert "price_anomaly" not in hot


def test_canonical_customer_map_collapses_variants_to_the_longest():
    m = canonical_customer_map(["Get Fresh", "Get Fresh Produce, LLC.", "Steve Testa", "Testa Produce"])
    assert m["Get Fresh"] == "Get Fresh Produce, LLC."
    assert m["Steve Testa"] == m["Testa Produce"] == "Testa Produce"
    assert same_customer("testa produce", "Steve Testa")
    assert not same_customer("Get Fresh", "Testa Produce")
