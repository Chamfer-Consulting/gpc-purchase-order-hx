"""Smoke tests. `pytest` from backend/. No DB needed for these — the analytics
stubs and auth checks don't touch Postgres."""

import datetime as dt
import os

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("ALLOWED_EMAIL_DOMAINS", "example.com")  # test tokens use @example.com

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


def test_email_allow_list():
    from app.auth import email_allowed

    assert email_allowed("anyone@example.com")          # allow-listed domain
    assert not email_allowed("outsider@gmail.com")      # not listed, no app_users row
    assert not email_allowed(None) and not email_allowed("no-at-sign")


def test_disallowed_email_is_rejected_with_a_typed_403(monkeypatch):
    import app.auth as _auth

    seen: list[str | None] = []
    monkeypatch.setattr(_auth, "_record_denied_signin", lambda email, sid: seen.append(email))

    tok = jwt.encode(
        {"sub": "x", "email": "outsider@gmail.com", "aud": "authenticated",
         "session_id": "sess-1",
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256",
    )
    r = client.get("/api/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_not_allowed"
    assert seen == ["outsider@gmail.com"]  # the denied attempt is logged to /audit


def test_hs256_token_accepted():
    """The legacy HS256 shared-secret path still verifies a well-formed token
    (the new asymmetric/JWKS path is selected only for ES256/RS256 headers)."""
    from fastapi.security import HTTPAuthorizationCredentials

    from app.auth import current_user

    user = current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token()))
    assert user.email == "test@example.com"


def test_config_needs_a_verification_path(monkeypatch):
    """Boot fails clearly if neither SUPABASE_URL (JWKS) nor SUPABASE_JWT_SECRET is set."""
    import pydantic

    from app.config import Settings

    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_filter_params_parsing():
    """FilterParams is the contract the SPA's useFilters mirrors — list filters
    arrive as repeated query keys, so a value with a comma stays intact."""
    from app.deps import filter_params

    fp = filter_params(
        start="2026-01-01", end="2026-03-31",
        customers=["Get Fresh", "Get Fresh Produce, Inc."],
        products=None, sizes=["4oz"], include_samples="1",
    )
    assert fp.start == "2026-01-01"
    assert fp.customers == ("Get Fresh", "Get Fresh Produce, Inc.")
    assert fp.sizes == ("4oz",)
    assert fp.include_samples is True
    assert fp.cache_key() == (
        "2026-01-01", "2026-03-31", ("Get Fresh", "Get Fresh Produce, Inc."), (), ("4oz",), True
    )


def test_filter_options_does_not_500_with_a_valid_token(monkeypatch):
    """Regression: the @cached key_fn was `lambda user:` but FastAPI calls the
    endpoint with keyword args only, so every /api/filters/options request raised
    TypeError -> 500 and left the customer/product/size MultiSelects empty."""
    import contextlib

    from app.cache import clear as _clear_cache

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_a, **_k):
            pass

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cur()

    @contextlib.contextmanager
    def _fake_conn():
        yield _Conn()

    monkeypatch.setattr("app.routers.filters.reused_conn", _fake_conn)
    _clear_cache()
    r = client.get("/api/filters/options", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json() == {"customers": [], "products": [], "sizes": []}


def test_oauth_callback_state_guard():
    # no valid signed state -> bounced back to the SPA, not a 500
    r = client.get("/auth/qbo/callback?code=x&realmId=1&state=bad", follow_redirects=False)
    assert r.status_code == 302 and "connect=qbo_state_mismatch" in r.headers["location"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/data-quality",
        "/api/matching/review",
        "/api/reconcile/queue",
        "/api/reconcile/po/1",
        "/api/review/queue",
        "/api/review/candidates",
        "/api/review/decisions",
        "/api/connections",
        "/api/po/1",
        "/api/po/1/detail",
        "/api/po/1/audit",
        "/api/po/1/revisions/2/diff",
        "/api/po/1/documents",
        "/api/po/1/documents/1",
        "/api/archive",
        "/api/invoices",
        "/api/pos",
        "/api/pricing",
        "/api/pricing/history?product=x&size=y",
        "/api/explore/pivot",
        "/api/explore/compare?a_start=2026-01-01&a_end=2026-01-31&b_start=2026-02-01&b_end=2026-02-28",
        "/api/settings/hidden-products",
        "/api/settings/hidden-customers",
        "/api/settings/views?kind=customers",
        "/api/settings/team",
        "/api/settings/hidden-invoices",
        "/api/audit",
        "/api/audit/options",
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
        ("post", "/api/po/1/line/1/math-ack", {"ack": True}),
        ("post", "/api/po/1/customer", {"customer_name": "x"}),
        ("post", "/api/po/1/regroup", {"standalone": True}),
        ("post", "/api/po/1/retry-extraction", {}),
        ("post", "/api/bulk/po-status", {"po_ids": [1], "status": "withdrawn"}),
        ("post", "/api/links", {"po_id": 1, "invoice_id": 1}),
        ("delete", "/api/links?po_id=1&invoice_id=1", None),
        ("post", "/api/matching/confirm", {"po_id": 1, "invoice_id": 1}),
        ("post", "/api/matching/reject", {"po_id": 1, "invoice_id": 1}),
        ("post", "/api/matching/confirm-batch", {"pairs": [{"po_id": 1, "invoice_id": 1}]}),
        ("post", "/api/po/1/documents/capture", {"sources": ["gmail"]}),
        ("post", "/api/po/1/documents/upload", {"filename": "x.pdf", "content_b64": "eA=="}),
        ("post", "/api/po/documents/backfill", {"sources": ["gmail"], "limit": 5}),
        ("delete", "/api/po/1/documents/1", None),
        ("post", "/api/pricing", {"rows": [], "delete": []}),
        ("post", "/api/settings/hidden-products", {"name": "x", "hidden": True}),
        ("post", "/api/settings/hidden-customers", {"name": "x", "hidden": True}),
        ("post", "/api/settings/views", {"kind": "customers", "name": "x", "config": {}}),
        ("delete", "/api/settings/views", {"kind": "customers", "name": "x"}),
        ("post", "/api/settings/team", {"email": "x@garfieldproduce.com", "role": "viewer"}),
        ("post", "/api/settings/hidden-invoices", {"qbo_invoice_id": "1", "hidden": True}),
        ("delete", "/api/settings/team/x@garfieldproduce.com", None),
    ],
)
def test_admin_mutations_require_auth(method, path, body):
    # client.request(...) (not client.delete(...)) — httpx's delete() takes no json=
    kw = {"json": body} if body is not None else {}
    m = method.upper()
    assert client.request(m, path, **kw).status_code == 403
    assert client.request(m, path, headers={"Authorization": "Bearer nope"}, **kw).status_code == 401

