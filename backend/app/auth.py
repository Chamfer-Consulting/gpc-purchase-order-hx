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
        # Supabase stamps the auth-session id on every access token it mints for
        # that session — stable across token refreshes, so the audit trail can
        # dedupe repeated "login" pings from the same browser session.
        self.session_id: str | None = claims.get("session_id")

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


# Emails we've already logged a denied sign-in for recently — the rejected
# client keeps retrying (react-query refetches), so cap it to one DB write per
# email per 30 min without even opening a connection in between.
_denied_logged: TTLCache = TTLCache(maxsize=256, ttl=1800)


def _record_denied_signin(email: str | None, session_id: str | None) -> None:
    key = (email or "").strip().lower()
    if not key or key in _denied_logged:
        return
    _denied_logged[key] = True
    try:
        from .reused_db import reused_conn
        from .services import audit

        with reused_conn() as conn:
            audit.record_auth_event(
                conn, email=key, event="login_denied", session_id=session_id,
                reason="email is not on the sign-in allow-list",
            )
            conn.commit()
    except Exception:  # audit is best-effort — never block the (correct) rejection
        _log.warning("could not record denied sign-in for %s", key, exc_info=True)


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
        _record_denied_signin(user.email, user.session_id)
        raise AccountNotAllowed(user.email)
    return user


# --- who may sign in + authorization tiers (app_users) --------------------

# field < viewer < editor < admin. No app_users row => 'viewer' (read-only): a
# new allowed user can look but not touch; 'field' / 'editor' / 'admin' must be
# granted. 'field' is the kiosk-only role (Product Yields harvest tablets) —
# it sits below 'viewer' and is never the implicit default, only ever an
# explicit grant, since it's *more* restricted than an ungranted signed-in user.
#
# 'external_viewer' sits at the same rank 0 floor, for the same "never
# implicit, more restricted than an ungranted user" reason, but it isn't
# actually a rung on this ladder — its access isn't "at least rank N", it's
# an admin-granted set of individual nav pages (app_users.external_pages),
# checked by require_page() below rather than by _ROLE_RANK comparison.
_ROLE_RANK = {"field": 0, "external_viewer": 0, "viewer": 1, "editor": 2, "admin": 3}
_DEFAULT_ROLE = "viewer"

# Nav pages (web/src/nav.tsx `to` paths) an admin can grant one at a time to
# an external_viewer account, via Settings -> Team. Keep in sync with
# nav.tsx's `externalViewable` flag — that's what builds the admin's
# checkbox list; this is the server-side allow-list set_team_member
# validates against and require_page checks membership against.
EXTERNAL_VIEWABLE_PAGES = (
    "/", "/customers", "/products", "/explore", "/lifecycle", "/pricing",
    "/yields", "/yields/entries",
)

# The subset of EXTERNAL_VIEWABLE_PAGES that actually share the PO/QBO
# customer/product/size metadata filters.router's /options serves — Pricing
# and both Yields pages have their own separate data model and never call
# useFilterOptions() on the frontend. An external_viewer granted only a
# Yields or Pricing page has no legitimate reason to pull the full
# cross-customer PO/QBO name lists, so /options checks against this
# narrower set rather than EXTERNAL_VIEWABLE_PAGES as a whole.
PO_ANALYTICS_PAGES = ("/", "/customers", "/products", "/explore", "/lifecycle")

# Per-email: (app_users role string, or "" for "no row"; external_pages list).
# Cached ~60s so the allow-list check, role check and page-grant check all
# share one small query per user per minute.
_NO_ROW: tuple[str, list[str]] = ("", [])
_role_cache: TTLCache = TTLCache(maxsize=512, ttl=60)


def _app_user_row(email: str | None) -> tuple[str, list[str]]:
    """(role, external_pages) from app_users, or ("", []) if there's no row."""
    key = (email or "").strip().lower()
    if not key:
        return _NO_ROW
    hit = _role_cache.get(key)
    if hit is not None:
        return hit
    try:
        from .reused_db import reused_conn

        with reused_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT role, external_pages FROM app_users WHERE lower(email) = %s", (key,))
            row = cur.fetchone()
            result = (row[0], list(row[1] or [])) if row and row[0] in _ROLE_RANK else _NO_ROW
    except Exception:
        # A transient DB blip must never be cached as "no row" — that would
        # wrongly deny an off-domain user's very next request (email_allowed
        # depends on this) for the full 60s TTL even once the DB recovers.
        # Return unrecognized-for-now without writing to the cache, so the
        # next request retries against the DB instead of being stuck.
        return _NO_ROW
    _role_cache[key] = result
    return result


def _app_user_role(email: str | None) -> str:
    """The email's app_users.role, or "" if there's no row. Cached."""
    return _app_user_row(email)[0]


def external_pages(email: str | None) -> list[str]:
    """The email's admin-granted nav-page list — always empty for every role
    other than external_viewer."""
    return _app_user_row(email)[1]


def clear_role_cache(email: str | None = None) -> None:
    """Drop cached role(s) after a Team change so it takes effect at once.
    Normalized the same way _app_user_row's cache key is (strip + lower) —
    an admin-typed email with incidental leading/trailing whitespace (e.g.
    pasted from a mail client) would otherwise evict a key that was never
    actually cached, leaving the real entry to expire on its own after the
    full 60s TTL instead of clearing immediately."""
    if email:
        _role_cache.pop(email.strip().lower(), None)
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
    if _app_user_role(key) != "":
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


require_viewer = require_role("viewer")
require_editor = require_role("editor")
require_admin = require_role("admin")


def require_page(*page_keys: str, bare: bool = False):
    """FastAPI dependency gating a specific nav page's data for external_viewer.

    Real staff (rank >= viewer — editor/admin too) always pass, completely
    unaffected either way. An external_viewer passes only if the admin
    granted at least one of `page_keys` (app_users.external_pages). Every
    other role (today, just 'field') passes when `bare=True` — for a route
    that already had a bare current_user floor the kiosk needs to keep
    reaching (see routers/yields.py) — and is denied when `bare=False`, the
    normal case for a route that used to sit behind require_viewer.
    """
    keys = set(page_keys)

    def _dep(user: AuthedUser = Depends(current_user)) -> AuthedUser:
        role = app_role(user.email)
        if _ROLE_RANK.get(role, -1) >= _ROLE_RANK["viewer"]:
            return user
        if role == "external_viewer":
            if keys & set(external_pages(user.email)):
                return user
            raise Forbidden(need="viewer", have=role)
        if bare:
            return user
        raise Forbidden(need="viewer", have=role)

    return _dep
