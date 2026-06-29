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
    engine = create_engine("postgresql+asyncpg://user:pass@localhost:5432/db")

    try:
        assert engine.url.drivername == "postgresql+asyncpg"
    finally:
        engine.sync_engine.dispose()


def test_repository_base_convention() -> None:
    assert BaseRepository.__name__ == "BaseRepository"
    assert Base.metadata is not None
