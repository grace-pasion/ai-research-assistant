from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://research:research@localhost:5432/research_db"
    literature_database_url: str | None = None
    jwt_secret: SecretStr = SecretStr("development-only-change-this-secret")
    jwt_expire_minutes: int = 60 * 24
    openai_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    admin_emails: str = ""
    openalex_email: str | None = None
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    daily_embedding_token_limit: int = Field(default=50_000, ge=1)
    storage_dir: str = "./uploads"
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_storage_bucket: str = "research-documents"
    cors_origins: str = "http://localhost:5173"
    approval_token_max_age_seconds: int = 900

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_list(self) -> set[str]:
        return {email.strip().casefold() for email in self.admin_emails.split(",") if email.strip()}

    @property
    def effective_literature_database_url(self) -> str:
        return self.literature_database_url or self.database_url

    @property
    def effective_supabase_key(self) -> SecretStr | None:
        for key in (self.supabase_secret_key, self.supabase_service_role_key):
            if key is not None and key.get_secret_value().strip():
                return key
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
