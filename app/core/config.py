from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    app_name: str = "Agentic Google Workspace Orchestrator"
    app_env: str = "development"
    log_level: str = "INFO"
    postgres_db: str = "workspace_orchestrator"
    postgres_user: str = "workspace"
    postgres_password: str = "development-only-password"
    database_url: str = (
        "postgresql+psycopg://workspace:development-only-password@localhost:5432/"
        "workspace_orchestrator"
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0)
    redis_url: str = "redis://localhost:6379/0"
    redis_key_namespace: str = Field(default="workspace-orchestrator", min_length=1)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    token_encryption_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    default_user_timezone: str = "Asia/Kolkata"
    default_meeting_duration_minutes: int = Field(default=30, ge=1, le=1440)
    oauth_state_ttl_seconds: int = Field(default=600, ge=60)
    session_ttl_seconds: int = Field(default=604800, ge=300)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
