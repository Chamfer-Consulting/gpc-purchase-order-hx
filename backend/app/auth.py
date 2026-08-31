"""Verify the Supabase-issued access token on `Authorization: Bearer <token>`.

Supabase's JWT signing-keys model (2025+) signs access tokens with an asymmetric
key — ES256 by default, RS256 optionally — and publishes the public keys at the
project's JWKS endpoint (`/auth/v1/.well-known/jwks.json`). We verify those
locally against the JWKS (cached), which means key rotation needs no redeploy.
Projects still on the legacy shared secret sign HS256; those verify against
SUPABASE_JWT_SECRET. The token's `alg` header picks the path. `aud` =
"authenticated" either way.
"""

import jwt
from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings
from .errors import Forbidden

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
    return AuthedUser(claims)


# --- authorization tiers (app_users) --------------------------------------

# viewer < editor < admin. No app_users row => 'editor' (see migration 0006):
# every existing signed-in user keeps working; 'admin' must be granted.
_ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}
_DEFAULT_ROLE = "editor"
_role_cache: TTLCache = TTLCache(maxsize=512, ttl=60)


def app_role(email: str | None) -> str:
    """The signed-in user's app role. Cached ~60s so it costs one small query per
    user per minute, not per request."""
    key = (email or "").lower()
    if not key:
        return "viewer"
    hit = _role_cache.get(key)
    if hit is not None:
        return hit
    role = _DEFAULT_ROLE
    try:
        from .reused_db import reused_conn

        with reused_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM app_users WHERE lower(email) = %s", (key,))
            row = cur.fetchone()
            if row and row[0] in _ROLE_RANK:
                role = row[0]
    except Exception:  # app_users missing / DB blip -> fall back to the default
        pass
    _role_cache[key] = role
    return role


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
