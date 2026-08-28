"""Smoke tests. Run: `pytest` from backend/ (needs a .env with a DB it can reach,
or set DATABASE_URL + SUPABASE_JWT_SECRET in the environment)."""

import datetime as dt
import os

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nonexistent")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_overview_requires_auth():
    assert client.get("/api/overview").status_code == 403  # no bearer


def test_overview_rejects_bad_token():
    r = client.get("/api/overview", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


@pytest.mark.skipif(
    "postgresql://localhost/nonexistent" in os.environ.get("DATABASE_URL", ""),
    reason="no real database configured",
)
def test_overview_with_valid_token():
    token = jwt.encode(
        {
            "sub": "test-user",
            "email": "test@example.com",
            "aud": "authenticated",
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        },
        os.environ["SUPABASE_JWT_SECRET"],
        algorithm="HS256",
    )
    r = client.get("/api/overview", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "kpis" in r.json()
