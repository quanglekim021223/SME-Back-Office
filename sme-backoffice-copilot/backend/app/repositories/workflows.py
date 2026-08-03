"""Workflow runtime persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.operations import AuditEvent, ReviewTask
from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.repositories.base import TenantScopedRepository


class WorkflowRuntimeRepository(TenantScopedRepository[WorkflowRun]):
    """Repository for durable workflow runtime records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowRun)

    async def get_for_tenant(
        self,
        *,
        tenant_id: UUID,
        object_id: UUID,  # workflow_run_id
    ) -> WorkflowRun | None:
        """Return a workflow run scoped to one tenant."""

        statement = select(WorkflowRun).where(
            WorkflowRun.id == object_id,
            WorkflowRun.tenant_id == tenant_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_latest_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> WorkflowRun | None:
        """Return the newest workflow run for one tenant-owned document."""

        statement = (
            select(WorkflowRun)
            .where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.document_id == document_id,
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_steps_for_run(
        self,
        *,
        tenant_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AgentStepExecution]:
        """Return tenant-owned step executions in durable execution order."""

        statement = (
            select(AgentStepExecution)
            .where(
                AgentStepExecution.tenant_id == tenant_id,
                AgentStepExecution.workflow_run_id == workflow_run_id,
            )
            .order_by(
                AgentStepExecution.created_at.asc(),
                AgentStepExecution.id.asc(),
            )
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_handoffs_for_run(
        self,
        *,
        tenant_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AgentHandoff]:
        """Return tenant-owned handoff edges in creation order."""

        statement = (
            select(AgentHandoff)
            .where(
                AgentHandoff.tenant_id == tenant_id,
                AgentHandoff.workflow_run_id == workflow_run_id,
            )
            .order_by(AgentHandoff.created_at.asc(), AgentHandoff.id.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_review_audit_events_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AuditEvent]:
        """Return human review audit events linked to a tenant-owned document."""

        invoice_result = await self.session.execute(
            select(Invoice.id).where(
                Invoice.tenant_id == tenant_id,
                Invoice.document_id == document_id,
            )
        )
        invoice_ids = set(invoice_result.scalars().all())

        review_filters = [
            ReviewTask.document_id == document_id,
            ReviewTask.workflow_run_id == workflow_run_id,
        ]
        if invoice_ids:
            review_filters.append(ReviewTask.invoice_id.in_(invoice_ids))
        review_result = await self.session.execute(
            select(ReviewTask).where(
                ReviewTask.tenant_id == tenant_id,
                or_(*review_filters),
            )
        )
        review_tasks = list(review_result.scalars().all())

        resource_ids: set[UUID] = {document_id, *invoice_ids}
        for task in review_tasks:
            for resource_id in (
                task.invoice_id,
                task.transaction_id,
                task.classification_proposal_id,
                task.reconciliation_id,
                task.insight_id,
            ):
                if resource_id is not None:
                    resource_ids.add(resource_id)

        statement = (
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action.like("review_task.%"),
                AuditEvent.resource_id.in_(resource_ids),
            )
            .options(selectinload(AuditEvent.actor_user))
            .order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

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
