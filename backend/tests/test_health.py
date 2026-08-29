"""Smoke tests. `pytest` from backend/. No DB needed for these — the analytics
stubs and auth checks don't touch Postgres."""

import datetime as dt
import os

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

from app.main import app  # noqa: E402

client = TestClient(app)


def _token() -> str:
    return jwt.encode(
        {
            "sub": "test-user",
            "email": "test@example.com",
            "aud": "authenticated",
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        },
        os.environ["SUPABASE_JWT_SECRET"],
        algorithm="HS256",
    )


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auth_required():
    assert client.get("/api/overview").status_code == 403  # no bearer
    assert client.get("/api/customers", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_filter_params_parsing():
    """FilterParams is the contract the SPA's useFilters mirrors."""
    from app.deps import filter_params

    fp = filter_params(
        start="2026-01-01", end="2026-03-31", customers="Get Fresh,Testa",
        products=None, sizes="4oz", include_samples="1",
    )
    assert fp.start == "2026-01-01"
    assert fp.customers == ("Get Fresh", "Testa")
    assert fp.sizes == ("4oz",)
    assert fp.include_samples is True
    assert fp.cache_key() == (
        "2026-01-01", "2026-03-31", ("Get Fresh", "Testa"), (), ("4oz",), True
    )


def test_oauth_callback_state_guard():
    # no valid signed state -> bounced back to the SPA, not a 500
    r = client.get("/auth/qbo/callback?code=x&realmId=1&state=bad", follow_redirects=False)
    assert r.status_code == 302 and "connect=qbo_state_mismatch" in r.headers["location"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/data-quality",
        "/api/matching/review",
        "/api/review/queue",
        "/api/review/candidates",
        "/api/review/decisions",
        "/api/connections",
        "/api/po/1",
        "/api/po/1/detail",
        "/api/po/1/audit",
        "/api/po/1/documents",
        "/api/po/1/documents/1",
        "/api/archive",
        "/api/invoices",
        "/api/pricing",
        "/api/pricing/history?product=x&size=y",
        "/api/settings/hidden-products",
        "/api/settings/views?kind=customers",
        "/api/overview",
        "/api/filters/options",
        "/api/customers",
        "/api/products",
    ],
)
def test_all_data_routes_require_auth(path):
    assert client.get(path).status_code == 403
    assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/po", {"header": {}, "items": []}),
        ("post", "/api/po/1/status", {"status": "cancelled"}),
        ("delete", "/api/po/1", {"reason": "x"}),
        ("post", "/api/po/1/restore", {}),
        ("post", "/api/po/1/line/1/void", {"voided": True}),
        ("post", "/api/po/1/customer", {"customer_name": "x"}),
        ("post", "/api/po/1/regroup", {"standalone": True}),
        ("post", "/api/links", {"po_id": 1, "invoice_id": 1}),
        ("delete", "/api/links?po_id=1&invoice_id=1", None),
        ("post", "/api/po/1/documents/capture", {"sources": ["gmail"]}),
        ("post", "/api/po/1/documents/upload", {"filename": "x.pdf", "content_b64": "eA=="}),
        ("post", "/api/po/documents/backfill", {"sources": ["gmail"], "limit": 5}),
        ("delete", "/api/po/1/documents/1", None),
        ("post", "/api/pricing", {"rows": [], "delete": []}),
        ("post", "/api/settings/hidden-products", {"product_name": "x", "hidden": True}),
        ("post", "/api/settings/views", {"kind": "customers", "name": "x", "config": {}}),
        ("delete", "/api/settings/views", {"name": "x"}),
    ],
)
def test_admin_mutations_require_auth(method, path, body):
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kw).status_code == 403
    assert getattr(client, method)(
        path, headers={"Authorization": "Bearer nope"}, **kw
    ).status_code == 401

