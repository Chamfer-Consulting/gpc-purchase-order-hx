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


@pytest.mark.parametrize("page", ["explore", "lifecycle"])
def test_analytics_stub_shape(page):
    r = client.get(f"/api/{page}", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["stub"] is True
    assert {"scope", "kpis", "charts", "tables", "notes", "attention"} <= body.keys()
    r2 = client.get(
        f"/api/{page}?start=2026-01-01&end=2026-03-31&customers=Get%20Fresh",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r2.json()["scope"]["start"] == "2026-01-01"


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
        "/api/overview",
    ],
)
def test_all_data_routes_require_auth(path):
    assert client.get(path).status_code == 403
    assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401

