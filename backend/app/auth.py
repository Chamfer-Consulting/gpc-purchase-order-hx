"""Verify the Supabase-issued JWT the SPA sends as `Authorization: Bearer <token>`.

Supabase signs access tokens HS256 with the project's JWT secret, `aud` =
"authenticated". We verify signature + exp + aud and hand the route the claims."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

_bearer = HTTPBearer(auto_error=True)


class AuthedUser:
    def __init__(self, claims: dict):
        self.claims = claims
        self.id: str = claims.get("sub", "")
        self.email: str | None = claims.get("email")
        self.role: str | None = claims.get("role")

    def __repr__(self) -> str:  # pragma: no cover
        return f"AuthedUser({self.email or self.id!r})"


def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> AuthedUser:
    s = get_settings()
    try:
        claims = jwt.decode(
            creds.credentials,
            s.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=s.supabase_jwt_aud,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthedUser(claims)
