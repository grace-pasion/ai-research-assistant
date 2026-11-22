from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://research:research@localhost:5432/research_db"
    literature_database_url: str = (
        "postgresql+psycopg://research:research@localhost:5432/literature_db"
    )
    jwt_secret: SecretStr = SecretStr("development-only-change-this-secret")
    jwt_expire_minutes: int = 60 * 24
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openalex_email: str | None = None
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    storage_dir: str = "./uploads"
    cors_origins: str = "http://localhost:5173"
    approval_token_max_age_seconds: int = 900

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
