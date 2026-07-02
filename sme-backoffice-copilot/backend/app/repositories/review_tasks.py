"""Review task persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import ReviewTask, ReviewTaskStatus, ReviewTaskType
from app.repositories.base import BaseRepository


class ReviewTaskRepository(BaseRepository[ReviewTask]):
    """Repository for tenant-scoped review tasks."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReviewTask)

    async def list_for_tenant(
        self,
        *,
        tenant_id: UUID,
        status_filter: ReviewTaskStatus | None = None,
        task_type: ReviewTaskType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReviewTask], int]:
        """Return review tasks and total count for one tenant."""

        base_statement = self._base_tenant_statement(
            tenant_id=tenant_id,
            status_filter=status_filter,
            task_type=task_type,
        )
        count_statement = select(func.count()).select_from(base_statement.subquery())
        total_result = await self.session.execute(count_statement)
        total = total_result.scalar_one()

        statement = (
            base_statement.order_by(
                ReviewTask.created_at.desc(),
                ReviewTask.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all()), total

    async def get_for_tenant(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        """Return one tenant-owned review task by id."""

        statement = select(ReviewTask).where(
            ReviewTask.tenant_id == tenant_id,
            ReviewTask.id == review_task_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def _base_tenant_statement(
        self,
        *,
        tenant_id: UUID,
        status_filter: ReviewTaskStatus | None,
        task_type: ReviewTaskType | None,
    ) -> Select[tuple[ReviewTask]]:
        """Build the shared tenant/filter statement."""

        statement = select(ReviewTask).where(ReviewTask.tenant_id == tenant_id)
        if status_filter is not None:
            statement = statement.where(ReviewTask.status == status_filter.value)
        if task_type is not None:
            statement = statement.where(ReviewTask.task_type == task_type.value)
        return statement
