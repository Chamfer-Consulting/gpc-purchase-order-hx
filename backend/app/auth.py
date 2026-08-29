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
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings

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
