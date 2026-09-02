"""Stateless OAuth `state` — the callback lands on the backend (not the SPA), so
there's no session to hold a nonce in. Sign a short-lived HS256 token with a
server-only secret (settings.state_secret: its own value, else the JWT secret,
else the DB URL); the callback verifies it before exchanging the code."""

import secrets
import time

import jwt

from .config import get_settings

_TTL = 600  # 10 minutes to complete the consent screen


def issue(purpose: str, actor: str | None = None) -> str:
    s = get_settings()
    claims = {
        "purpose": purpose,
        "nonce": secrets.token_urlsafe(8),
        "exp": int(time.time()) + _TTL,
    }
    if actor:
        claims["actor"] = actor  # who started the connect — read back in the callback
    return jwt.encode(claims, s.state_secret, algorithm="HS256")


def read(token: str, purpose: str) -> dict | None:
    """Verified claims for a state token, or None if it's bad / for another purpose."""
    s = get_settings()
    try:
        claims = jwt.decode(token, s.state_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("purpose") == purpose else None


def verify(token: str, purpose: str) -> bool:
    return read(token, purpose) is not None
