"""Base repository convention for tenant-scoped data access.

Repositories should own persistence queries. Services and workflows should use
repositories instead of issuing ad hoc SQLAlchemy operations directly.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class BaseRepository[ModelT: Base]:
    """Small repository base around a SQLAlchemy async session.

    This class intentionally avoids committing transactions. Application
    services own transaction boundaries so multiple repository operations can be
    committed or rolled back together.
    """

    def __init__(self, session: AsyncSession, model_type: type[ModelT]) -> None:
        self.session = session
        self.model_type = model_type

    async def get(self, object_id: object) -> ModelT | None:
        """Return one model instance by primary key."""

        return await self.session.get(self.model_type, object_id)

    def add(self, instance: ModelT) -> ModelT:
        """Stage a model instance for insertion."""

        self.session.add(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Stage a model instance for deletion."""

        await self.session.delete(instance)
