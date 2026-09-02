"""Audit history — the cross-system activity feed. No DB in CI, so this covers the
admin gate and the pure reason-derivation helper; the DB-backed feed is exercised
by the manual verification in the plan."""

import datetime as _dt
import os

import jwt as _jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("ALLOWED_EMAIL_DOMAINS", "example.com")

import app.auth as _auth  # noqa: E402
from app.main import app  # noqa: E402
from app.services.audit import derive_reason  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_FAKE_ROLES = {"editor@example.com": "editor", "admin@example.com": "admin"}


@pytest.fixture()
def roles(monkeypatch):
    """Fake app_users lookups for this test only (no DB in CI). monkeypatch undoes
    it afterwards so the module-global patch can't leak into other test files."""
    monkeypatch.setattr(_auth, "_app_user_role",
                        lambda e: _FAKE_ROLES.get((e or "").lower(), ""))


def _tok(email: str) -> str:
    return _jwt.encode(
        {"sub": "u", "email": email, "aud": "authenticated",
         "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)},
        os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256",
    )


@pytest.mark.parametrize("path", ["/api/audit", "/api/audit/options"])
def test_audit_is_admin_only(roles, path):
    assert client.get(path).status_code == 403                       # no bearer
    r = client.get(path, headers={"Authorization": f"Bearer {_tok('editor@example.com')}"})
    assert r.status_code == 403 and r.json()["detail"]["need"] == "admin"


def test_admin_gets_past_the_gate(roles):
    # No Postgres in CI, so the query itself 500s — the point is the admin role is
    # accepted (not a 403).
    r = client.get("/api/audit", headers={"Authorization": f"Bearer {_tok('admin@example.com')}"})
    assert r.status_code != 403


def test_derive_reason_prefers_after_and_known_keys():
    assert derive_reason({"status_reason": "old"}, {"status_reason": "customer cancelled"}) == "customer cancelled"
    assert derive_reason(None, {"void_reason": "  duplicate line  "}) == "duplicate line"
    assert derive_reason({"reason": "backfill"}, {"po_number": "1234"}) == "backfill"
    assert derive_reason({"note": "few-shot fix"}, None) == "few-shot fix"
    assert derive_reason(None, None) is None
    assert derive_reason({}, {"total": 10}) is None
