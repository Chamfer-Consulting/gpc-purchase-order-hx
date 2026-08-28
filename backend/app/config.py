"""Environment-driven settings. Nothing is read from st.secrets here — this process
never imports streamlit."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres — the Supabase TRANSACTION pooler (:6543) for this API. The pipeline
    # scripts use the session connection instead (see docs/REBUILD-SETUP.md §1).
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_min: int = Field(1, alias="DB_POOL_MIN")
    db_pool_max: int = Field(8, alias="DB_POOL_MAX")

    # Supabase
    supabase_url: str = Field("", alias="SUPABASE_URL")
    supabase_service_key: str = Field("", alias="SUPABASE_SERVICE_KEY")
    supabase_jwt_secret: str = Field(..., alias="SUPABASE_JWT_SECRET")
    supabase_jwt_aud: str = Field("authenticated", alias="SUPABASE_JWT_AUD")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
