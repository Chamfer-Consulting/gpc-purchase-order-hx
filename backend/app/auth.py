"""Verify the Supabase-issued access token on `Authorization: Bearer <token>`.

Supabase's JWT signing-keys model (2025+) signs access tokens with an asymmetric
key — ES256 by default, RS256 optionally — and publishes the public keys at the
project's JWKS endpoint (`/auth/v1/.well-known/jwks.json`). We verify those
locally against the JWKS (cached), which means key rotation needs no redeploy.
Projects still on the legacy shared secret sign HS256; those verify against
SUPABASE_JWT_SECRET. The token's `alg` header picks the path. `aud` =
"authenticated" either way.
"""

import logging

import jwt
from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings
from .errors import AccountNotAllowed, Forbidden

_log = logging.getLogger("uvicorn.error")

_bearer = HTTPBearer(auto_error=True)
_ASYMMETRIC = ("ES256", "RS256", "EdDSA")

_jwk_client: PyJWKClient | None = None


class AuthedUser:
    def __init__(self, claims: dict):
        self.claims = claims
        self.id: str = claims.get("sub", "")
        self.email: str | None = claims.get("email")
        self.role: str | None = claims.get("role")

    def __repr__(self) -> str:  # pragma: no cover
        return f"AuthedUser({self.email or self.id!r})"


def _jwks() -> PyJWKClient | None:
    """Lazily built JWKS client. Caches keys in memory; PyJWKClient refetches on a
    cache miss (an unseen `kid`), so a rotated-in key is picked up automatically."""
    global _jwk_client
    if _jwk_client is not None:
        return _jwk_client
    url = get_settings().jwks_url
    if not url:
        return None
    _jwk_client = PyJWKClient(url, cache_keys=True, max_cached_keys=8, lifespan=600)
    return _jwk_client


def _decode(token: str) -> dict:
    s = get_settings()
    common = {"audience": s.supabase_jwt_aud, "options": {"require": ["exp", "sub"]}}
    alg = jwt.get_unverified_header(token).get("alg", "")

    if alg in _ASYMMETRIC:
        client = _jwks()
        if client is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "server has no SUPABASE_URL / JWKS to verify an asymmetric token",
            )
        try:
            key = client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as e:  # JWKS endpoint unreachable
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"cannot reach JWKS: {e}")
        return jwt.decode(token, key, algorithms=list(_ASYMMETRIC), **common)

    # HS256 — legacy shared secret / "shared secret" signing key.
    if not s.supabase_jwt_secret:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "server has no SUPABASE_JWT_SECRET to verify an HS256 token",
        )
    return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], **common)


def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> AuthedUser:
    try:
        claims = _decode(creds.credentials)
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = AuthedUser(claims)
    if not email_allowed(user.email):
        raise AccountNotAllowed(user.email)
    return user


# --- who may sign in + authorization tiers (app_users) --------------------

# viewer < editor < admin. No app_users row => 'viewer' (read-only): a new
# allowed user can look but not touch; 'editor' / 'admin' must be granted.
_ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}
_DEFAULT_ROLE = "viewer"

# Per-email: the app_users role string, or "" for "no row". Cached ~60s so both
# the allow-list check and the role check cost one small query per user per minute.
_NO_ROW = ""
_role_cache: TTLCache = TTLCache(maxsize=512, ttl=60)


def _app_user_role(email: str | None) -> str:
    """The email's app_users.role, or "" if there's no row. Cached."""
    key = (email or "").lower()
    if not key:
        return _NO_ROW
    hit = _role_cache.get(key)
    if hit is not None:
        return hit
    role = _NO_ROW
    try:
        from .reused_db import reused_conn

        with reused_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM app_users WHERE lower(email) = %s", (key,))
            row = cur.fetchone()
            if row and row[0] in _ROLE_RANK:
                role = row[0]
    except Exception:  # app_users missing / DB blip
        pass
    _role_cache[key] = role
    return role


def clear_role_cache(email: str | None = None) -> None:
    """Drop cached role(s) after a Team change so it takes effect at once."""
    if email:
        _role_cache.pop(email.lower(), None)
    else:
        _role_cache.clear()


def email_allowed(email: str | None) -> bool:
    """Gate on identity (not role): the email's domain is allow-listed, OR the
    email is explicitly listed, OR it has an app_users row. With both env lists
    empty (dev), only app_users members pass — a safe fail-closed default."""
    key = (email or "").strip().lower()
    if not key or "@" not in key:
        return False
    s = get_settings()
    domain = key.rsplit("@", 1)[1]
    if domain in s.allow_domains or key in s.allow_emails:
        return True
    if _app_user_role(key) != _NO_ROW:
        return True
    if not s.allow_domains and not s.allow_emails:
        _log.warning(
            "email allow-list not configured (ALLOWED_EMAIL_DOMAINS / ALLOWED_EMAILS) "
            "— only app_users members can sign in; %s rejected", key,
        )
    return False


def app_role(email: str | None) -> str:
    """The signed-in user's app role — the app_users row's role, else viewer."""
    return _app_user_role(email) or _DEFAULT_ROLE


def require_role(minimum: str):
    """FastAPI dependency: 403 (Forbidden) unless the caller's app role is at least
    `minimum`. Returns the AuthedUser so routes can keep `user: ... = Depends(...)`."""
    floor = _ROLE_RANK[minimum]

    def _dep(user: AuthedUser = Depends(current_user)) -> AuthedUser:
        role = app_role(user.email)
        if _ROLE_RANK.get(role, 0) < floor:
            raise Forbidden(need=minimum, have=role)
        return user

    return _dep


require_editor = require_role("editor")
require_admin = require_role("admin")
