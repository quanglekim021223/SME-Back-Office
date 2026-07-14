"""Persistence queries for durable workflow jobs and outbox delivery."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jobs import OutboxEvent, OutboxEventStatus, WorkflowJob
from app.models.workflow import WorkflowRun
from app.repositories.workflows import WorkflowRuntimeRepository


class WorkflowJobRepository(WorkflowRuntimeRepository):
    """Store workflow state, durable jobs, and outbox events in one session."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    def add_workflow_job(self, job: WorkflowJob) -> WorkflowJob:
        self.session.add(job)
        return job

    def add_outbox_event(self, event: OutboxEvent) -> OutboxEvent:
        self.session.add(event)
        return event

    async def get_job(
        self,
        job_id: UUID,
        *,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        statement = select(WorkflowJob).where(WorkflowJob.id == job_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_job_for_tenant(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        """Return one durable job only when it belongs to the current tenant."""

        statement = select(WorkflowJob).where(
            WorkflowJob.id == job_id,
            WorkflowJob.tenant_id == tenant_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_job_for_workflow_run(
        self,
        workflow_run_id: UUID,
        *,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        statement = select(WorkflowJob).where(
            WorkflowJob.workflow_run_id == workflow_run_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_dispatchable_outbox(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[OutboxEvent]:
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxEventStatus.PENDING.value,
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def list_stale_running_jobs(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[WorkflowJob]:
        statement = (
            select(WorkflowJob)
            .where(
                WorkflowJob.status == "running",
                WorkflowJob.lease_expires_at.is_not(None),
                WorkflowJob.lease_expires_at < now,
            )
            .order_by(WorkflowJob.lease_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def list_jobs_for_metrics(self, *, tenant_id: UUID) -> list[WorkflowJob]:
        result = await self.session.execute(
            select(WorkflowJob).where(WorkflowJob.tenant_id == tenant_id)
        )
        return list(result.scalars())

    async def cancel_pending_outbox(self, workflow_job_id: UUID) -> None:
        result = await self.session.execute(
            select(OutboxEvent).where(
                OutboxEvent.workflow_job_id == workflow_job_id,
                OutboxEvent.status == OutboxEventStatus.PENDING.value,
            )
        )
        for event in result.scalars():
            event.status = OutboxEventStatus.CANCELLED.value

    async def get_workflow_run_unscoped(
        self,
        workflow_run_id: UUID,
    ) -> WorkflowRun | None:
        return await self.session.get(WorkflowRun, workflow_run_id)
