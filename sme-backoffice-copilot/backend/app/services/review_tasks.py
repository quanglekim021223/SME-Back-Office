"""Application service for read-only review task queries."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import ReviewTask, ReviewTaskStatus, ReviewTaskType
from app.repositories.review_tasks import ReviewTaskRepository


@dataclass(frozen=True)
class ReviewTaskListResult:
    """Review task list query result."""

    tasks: list[ReviewTask]
    total: int
    limit: int
    offset: int


class ReviewTaskQueryService:
    """Read-only service for tenant-scoped review tasks."""

    def __init__(self, repository: ReviewTaskRepository) -> None:
        self.repository = repository

    @classmethod
    def from_session(cls, session: AsyncSession) -> ReviewTaskQueryService:
        """Create the service from a SQLAlchemy session."""

        return cls(repository=ReviewTaskRepository(session))

    async def list_review_tasks(
        self,
        *,
        tenant_id: UUID,
        status_filter: ReviewTaskStatus | None = None,
        task_type: ReviewTaskType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewTaskListResult:
        """Return review tasks for one tenant."""

        tasks, total = await self.repository.list_for_tenant(
            tenant_id=tenant_id,
            status_filter=status_filter,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
        return ReviewTaskListResult(
            tasks=tasks,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_review_task(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        """Return one tenant-owned review task by id."""

        return await self.repository.get_for_tenant(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
        )
