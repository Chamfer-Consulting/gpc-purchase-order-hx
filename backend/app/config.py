"""Environment-driven settings. Nothing is read from st.secrets here — this process
never imports streamlit."""

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres — the Supabase TRANSACTION pooler (:6543) for this API. The pipeline
    # scripts use the session connection instead (see docs/REBUILD-SETUP.md §1).
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_min: int = Field(1, alias="DB_POOL_MIN")
    db_pool_max: int = Field(8, alias="DB_POOL_MAX")

    # Supabase project URL, e.g. https://<ref>.supabase.co
    supabase_url: str = Field("", alias="SUPABASE_URL")

    # Backend API key for Supabase REST / Storage. Supabase's 2025 key model: the
    # new secret key (sb_secret_...) replaces the legacy service_role JWT; both
    # work until end of 2026. Accept either env name.
    supabase_service_key: str = Field(
        "", validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY")
    )

    # User access-token verification. Supabase's new JWT signing keys are
    # asymmetric (ES256 / RS256) and published at the project's JWKS endpoint —
    # verified locally, rotated with no redeploy. Projects still on the legacy
    # shared secret sign HS256; we verify those against SUPABASE_JWT_SECRET.
    # Set at least one path: SUPABASE_URL (→ JWKS) and/or SUPABASE_JWT_SECRET.
    supabase_jwt_secret: str = Field("", alias="SUPABASE_JWT_SECRET")
    supabase_jwks_url: str = Field("", alias="SUPABASE_JWKS_URL")
    supabase_jwt_aud: str = Field("authenticated", alias="SUPABASE_JWT_AUD")

    # HMAC key for the stateless OAuth `state` token (oauth_state.py). Its own
    # value if set, else the JWT secret, else the DB URL — server-only either way.
    oauth_state_secret: str = Field("", alias="OAUTH_STATE_SECRET")

    # CORS — comma-separated list of allowed frontend origins.
    allowed_origins: str = Field("http://localhost:5173", alias="ALLOWED_ORIGINS")
    # Where OAuth callbacks redirect the browser back to once tokens are stored.
    # Defaults to the first allowed origin.
    frontend_base: str = Field("", alias="FRONTEND_BASE")

    # Shared with the pipeline (used by the reused modules / OAuth callbacks).
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    gmail_client_id: str = Field("", alias="GMAIL_CLIENT_ID")
    gmail_client_secret: str = Field("", alias="GMAIL_CLIENT_SECRET")
    gmail_redirect_uri: str = Field("", alias="GMAIL_REDIRECT_URI")
    qbo_client_id: str = Field("", alias="QBO_CLIENT_ID")
    qbo_client_secret: str = Field("", alias="QBO_CLIENT_SECRET")
    qbo_redirect_uri: str = Field("", alias="QBO_REDIRECT_URI")
    qbo_environment: str = Field("sandbox", alias="QBO_ENVIRONMENT")

    env: str = Field("dev", alias="ENV")

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def frontend(self) -> str:
        return (self.frontend_base or (self.origins[0] if self.origins else "")).rstrip("/")

    @property
    def jwks_url(self) -> str:
        """Where to fetch the project's public JWT signing keys. Explicit override
        wins; otherwise derived from the project URL."""
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return ""

    @property
    def state_secret(self) -> str:
        return self.oauth_state_secret or self.supabase_jwt_secret or self.database_url

    @model_validator(mode="after")
    def _need_a_verification_path(self) -> "Settings":
        if not self.supabase_jwt_secret and not self.jwks_url:
            raise ValueError(
                "No way to verify access tokens: set SUPABASE_URL (asymmetric JWT "
                "signing keys, verified via JWKS) and/or SUPABASE_JWT_SECRET "
                "(legacy HS256 shared secret)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
