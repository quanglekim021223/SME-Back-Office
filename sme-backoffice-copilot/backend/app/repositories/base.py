"""Base repository convention for tenant-scoped data access.

Repositories should own persistence queries. Services and workflows should use
repositories instead of issuing ad hoc SQLAlchemy operations directly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
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


class TenantScopedRepository[ModelT: Base](BaseRepository[ModelT]):
    """Repository base that enforces tenant isolation on every fetch.

    Subclasses are expected to serve models that carry a ``tenant_id`` column.
    All single-record lookups **must** go through :meth:`get_for_tenant` so that
    a caller who knows a foreign UUID cannot silently read another tenant's data.
    """

    #: Name of the ``tenant_id`` column on the managed model.  Override in
    #: subclasses if the column uses a different attribute name.
    _tenant_id_attr: str = "tenant_id"

    async def get_for_tenant(
        self,
        *,
        tenant_id: UUID,
        object_id: Any,
    ) -> ModelT | None:
        """Return one model instance scoped to the given tenant.

        Returns ``None`` when the record does not exist **or** belongs to a
        different tenant, making cross-tenant probing indistinguishable from a
        missing record.
        """

        tenant_col = getattr(self.model_type, self._tenant_id_attr)
        pk_col = self.model_type.__mapper__.primary_key[0]
        pk_attr = self.model_type.__mapper__.get_property_by_column(pk_col).key
        model_pk_attr = getattr(self.model_type, pk_attr)

        statement = select(self.model_type).where(
            tenant_col == tenant_id,
            model_pk_attr == object_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

