import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import async_session_factory, create_engine
from app.models.base import Base
from app.repositories.base import BaseRepository


def test_settings_include_database_configuration() -> None:
    settings = Settings()

    assert settings.database_url
    assert settings.database_echo is False


def test_database_session_factory_uses_async_sessions() -> None:
    assert async_session_factory.class_ is AsyncSession


def test_create_engine_uses_async_driver_url() -> None:
    engine = create_engine(
        "postgresql+asyncpg://user:pass@localhost:5432/db",
        pool_size=3,
        max_overflow=1,
    )

    try:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert engine.sync_engine.pool.size() == 3
    finally:
        engine.sync_engine.dispose()


def test_hosted_settings_require_tls_for_database_and_redis() -> None:
    settings = Settings(
        _env_file=None,
        app_env="staging",
        database_url="postgresql+asyncpg://user:pass@host/database?ssl=require",
        celery_broker_url="rediss://:token@host:6379/0",
        celery_result_backend="rediss://:token@host:6379/0",
        provider_rate_limit_redis_url="rediss://:token@host:6379/0",
    )

    assert settings.database_pool_size == 5


def test_hosted_settings_reject_plaintext_redis() -> None:
    with pytest.raises(ValidationError, match="CELERY_BROKER_URL"):
        Settings(
            _env_file=None,
            app_env="staging",
            database_url="postgresql+asyncpg://user:pass@host/database?ssl=require",
            celery_broker_url="redis://host:6379/0",
            celery_result_backend="rediss://:token@host:6379/0",
            provider_rate_limit_redis_url="rediss://:token@host:6379/0",
        )


def test_repository_base_convention() -> None:
    assert BaseRepository.__name__ == "BaseRepository"
    assert Base.metadata is not None
