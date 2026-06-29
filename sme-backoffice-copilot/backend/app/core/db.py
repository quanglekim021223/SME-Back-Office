"""Database engine and session factory.

Repositories and services consume ``get_db_session``; route handlers should not
construct engines or issue raw connection management.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the async SQLAlchemy engine for the configured database."""

    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
    )


engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
)
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped SQLAlchemy session."""

    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose database connections during application shutdown or tests."""

    await engine.dispose()
