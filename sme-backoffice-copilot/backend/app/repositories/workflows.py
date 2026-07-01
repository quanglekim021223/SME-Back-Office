"""Workflow runtime persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.repositories.base import BaseRepository


class WorkflowRuntimeRepository(BaseRepository[WorkflowRun]):
    """Repository for durable workflow runtime records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowRun)

    async def get_for_tenant(
        self,
        *,
        tenant_id: UUID,
        workflow_run_id: UUID,
    ) -> WorkflowRun | None:
        """Return a workflow run scoped to one tenant."""

        statement = select(WorkflowRun).where(
            WorkflowRun.id == workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def add_workflow_run(self, workflow_run: WorkflowRun) -> WorkflowRun:
        """Stage a workflow run for insertion."""

        return self.add(workflow_run)

    def add_step_execution(
        self,
        step_execution: AgentStepExecution,
    ) -> AgentStepExecution:
        """Stage an agent step execution for insertion."""

        self.session.add(step_execution)
        return step_execution

    def add_handoff(self, handoff: AgentHandoff) -> AgentHandoff:
        """Stage an agent handoff for insertion."""

        self.session.add(handoff)
        return handoff

    async def commit(self) -> None:
        """Commit staged runtime records."""

        await self.session.commit()
