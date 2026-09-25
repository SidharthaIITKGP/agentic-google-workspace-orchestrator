import pytest

from app.core.config import Settings


def test_infrastructure_settings_have_safe_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(_env_file=None)

    assert settings.postgres_db == "workspace_orchestrator"
    assert settings.postgres_user == "workspace"
    assert settings.postgres_password == "development-only-password"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "localhost:5432" in settings.database_url
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.redis_key_namespace == "workspace-orchestrator"
    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 10
    assert settings.dependency_timeout_seconds == 2.0
    assert settings.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.embedding_dimensions == 384
    assert settings.embedding_warmup_enabled is False
    assert settings.index_stale_after_minutes == 15


def test_infrastructure_settings_accept_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_DB", "custom_db")
    monkeypatch.setenv("POSTGRES_USER", "custom_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "custom_password")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://custom_user:custom_password@db:5432/custom_db",
    )
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/1")

    settings = Settings(_env_file=None)

    assert settings.postgres_db == "custom_db"
    assert settings.postgres_user == "custom_user"
    assert settings.postgres_password == "custom_password"
    assert settings.database_url.endswith("@db:5432/custom_db")
    assert settings.redis_url == "redis://redis:6379/1"
