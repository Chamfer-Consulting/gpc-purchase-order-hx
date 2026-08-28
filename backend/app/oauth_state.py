"""Stateless OAuth `state` — the callback lands on the backend (not the SPA), so
there's no session to hold a nonce in. Sign a short-lived token with the Supabase
JWT secret; the callback verifies it before exchanging the code."""

import secrets
import time

import jwt

from .config import get_settings

_TTL = 600  # 10 minutes to complete the consent screen


def issue(purpose: str) -> str:
    s = get_settings()
    return jwt.encode(
        {"purpose": purpose, "nonce": secrets.token_urlsafe(8), "exp": int(time.time()) + _TTL},
        s.supabase_jwt_secret,
        algorithm="HS256",
    )


def verify(token: str, purpose: str) -> bool:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return claims.get("purpose") == purpose
