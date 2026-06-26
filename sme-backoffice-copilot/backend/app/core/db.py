"""Database engine and session factory.

Repositories and services consume ``get_db_session``; route handlers should not
construct engines or issue raw connection management.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped SQLAlchemy session."""

    async with async_session_factory() as session:
        yield session
