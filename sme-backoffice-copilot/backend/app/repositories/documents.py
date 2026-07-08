"""Document persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentArtifact
from app.repositories.base import TenantScopedRepository


class DocumentRepository(TenantScopedRepository[Document]):
    """Repository for document metadata and artifacts.

    All single-document lookups go through :meth:`get_for_tenant` to enforce
    tenant isolation — a caller who knows a foreign document UUID cannot read
    another tenant's document.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_by_tenant_and_content_hash(
        self,
        *,
        tenant_id: UUID,
        content_hash: str,
    ) -> Document | None:
        """Return an existing document for a tenant/content hash pair."""

        statement = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self,
        *,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        """Return paginated documents and total count for one tenant."""

        from sqlalchemy import func

        base_statement = select(Document).where(Document.tenant_id == tenant_id)
        count_statement = select(func.count()).select_from(base_statement.subquery())
        total_result = await self.session.execute(count_statement)
        total = total_result.scalar_one()

        statement = (
            base_statement.order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all()), total

    def add_artifact(self, artifact: DocumentArtifact) -> DocumentArtifact:
        """Stage a document artifact for insertion."""

        self.session.add(artifact)
        return artifact
