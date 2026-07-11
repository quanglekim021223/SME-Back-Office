"""Worker-side execution of queued document processing commands."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.jobs.contracts import DocumentProcessingCommand
from app.models.document import DocumentType
from app.models.workflow import WorkflowRun
from app.observability.tracing import build_trace_provider_from_settings
from app.providers import ProviderPrivacyContext
from app.providers.factory import (
    build_llm_provider_from_settings,
    build_ocr_provider_from_settings,
    build_provider_privacy_gate_from_settings,
    build_provider_routing_config_from_settings,
)
from app.providers.routing import ProviderRuntime
from app.repositories.workflows import WorkflowRuntimeRepository
from app.services.bank_statement_import import BankStatementCsvImportService
from app.services.document_events import DocumentIngested
from app.services.workflow_outputs import (
    SqlAlchemyWorkflowOutputPersistence,
    WorkflowOutputPersistenceService,
)
from app.workflows.contracts import WorkflowStage, WorkflowState, WorkflowStateStatus
from app.workflows.replay import ReplayScenario, WorkflowReplayRunner
from app.workflows.runtime import WorkflowProgressObserver, WorkflowRuntimeService

logger = logging.getLogger("app.workflow")


class DocumentProcessingWorkflowExecutor:
    """Execute queued document workflows with a fresh database session."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        progress_observer: WorkflowProgressObserver | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.progress_observer = progress_observer

    async def execute(
        self,
        command: DocumentProcessingCommand,
        *,
        mark_failed: bool = True,
    ) -> None:
        """Load the durable run and execute it outside the original HTTP request."""

        async with self.session_factory() as session:
            repository = WorkflowRuntimeRepository(session)
            workflow_run = await repository.get_for_tenant(
                tenant_id=command.tenant_id,
                object_id=command.workflow_run_id,
            )
            if workflow_run is None:
                logger.warning(
                    "workflow.job.skipped_missing_run",
                    extra={
                        "event": "workflow.job.skipped_missing_run",
                        "workflow_run_id": str(command.workflow_run_id),
                        "document_id": str(command.document_id),
                        "correlation_id": command.correlation_id,
                    },
                )
                return

            try:
                state = WorkflowState.model_validate(workflow_run.state or {})
                if command.document_type == DocumentType.BANK_STATEMENT.value:
                    await self._run_bank_statement(
                        session=session,
                        runtime=WorkflowRuntimeService(
                            repository,
                            progress_observer=self.progress_observer,
                        ),
                        workflow_run=workflow_run,
                        state=state,
                        command=command,
                    )
                else:
                    await self._run_invoice(
                        session=session,
                        workflow_run=workflow_run,
                        state=state,
                        command=command,
                    )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                if mark_failed:
                    await self._mark_failed(
                        session=session,
                        command=command,
                        error=exc,
                    )
                raise

    async def record_retry(
        self,
        command: DocumentProcessingCommand,
        *,
        error: Exception,
    ) -> None:
        """Persist queue retry state before Celery schedules the next attempt."""

        async with self.session_factory() as session:
            repository = WorkflowRuntimeRepository(session)
            workflow_run = await repository.get_for_tenant(
                tenant_id=command.tenant_id,
                object_id=command.workflow_run_id,
            )
            if workflow_run is None:
                return
            state = WorkflowState.model_validate(workflow_run.state or {})
            state.max_retries = self.settings.celery_task_max_retries
            WorkflowRuntimeService(
                repository,
                progress_observer=self.progress_observer,
            ).request_retry(
                workflow_run=workflow_run,
                state=state,
                agent_name="workflow_queue",
                error_code="ERR_WORKFLOW_JOB_RETRY",
                error_message=str(error),
            )
            await session.commit()

    async def mark_failed_from_exception(
        self,
        command: DocumentProcessingCommand,
        *,
        error: Exception,
    ) -> None:
        """Persist terminal failure after the worker has exhausted retries."""

        async with self.session_factory() as session:
            await self._mark_failed(session=session, command=command, error=error)

    async def _run_invoice(
        self,
        *,
        session: AsyncSession,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        command: DocumentProcessingCommand,
    ) -> None:
        trace_provider = build_trace_provider_from_settings(self.settings)
        provider_runtime = ProviderRuntime(
            build_provider_routing_config_from_settings(self.settings),
            privacy_gate=build_provider_privacy_gate_from_settings(self.settings),
        )
        runner = WorkflowReplayRunner(
            persistence=WorkflowRuntimeRepository(session),
            provider_runtime=provider_runtime,
            llm_provider=build_llm_provider_from_settings(self.settings),
            ocr_provider=build_ocr_provider_from_settings(self.settings),
            provider_privacy_context=ProviderPrivacyContext(tenant_allows_cloud=True),
            trace_provider=trace_provider,
            progress_observer=self.progress_observer,
        )
        result = await runner.run(
            state=state,
            scenario=ReplayScenario.HAPPY_PATH,
            correlation_id=command.correlation_id,
            workflow_run=workflow_run,
        )
        await WorkflowOutputPersistenceService(
            SqlAlchemyWorkflowOutputPersistence(session),
            trace_provider=trace_provider,
        ).persist_invoice_review_from_workflow_result(result)

    async def _run_bank_statement(
        self,
        *,
        session: AsyncSession,
        runtime: WorkflowRuntimeService,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        command: DocumentProcessingCommand,
    ) -> None:
        runtime.resume_workflow(
            workflow_run=workflow_run,
            state=state,
            correlation_id=command.correlation_id,
        )
        await BankStatementCsvImportService(session).import_document(
            self._event_from_command(command)
        )
        runtime.update_workflow_status(
            workflow_run=workflow_run,
            state=state,
            status=WorkflowStateStatus.COMPLETED,
            stage=WorkflowStage.COMPLETED,
        )

    async def _mark_failed(
        self,
        *,
        session: AsyncSession,
        command: DocumentProcessingCommand,
        error: Exception,
    ) -> None:
        repository = WorkflowRuntimeRepository(session)
        workflow_run = await repository.get_for_tenant(
            tenant_id=command.tenant_id,
            object_id=command.workflow_run_id,
        )
        if workflow_run is None:
            return
        state = WorkflowState.model_validate(workflow_run.state or {})
        WorkflowRuntimeService(
            repository,
            progress_observer=self.progress_observer,
        ).mark_failed(
            workflow_run=workflow_run,
            state=state,
            error_code="ERR_WORKFLOW_EXECUTION_FAILED",
            error_message=str(error),
        )
        await session.commit()

    @staticmethod
    def _event_from_command(command: DocumentProcessingCommand) -> DocumentIngested:
        return DocumentIngested(
            event_id=command.event_id,
            tenant_id=command.tenant_id,
            document_id=command.document_id,
            document_type=command.document_type,
            content_hash=command.content_hash,
            storage_uri=command.storage_uri,
            malware_scan_status=command.malware_scan_status,
            local_path=command.local_path,
            correlation_id=command.correlation_id,
        )
