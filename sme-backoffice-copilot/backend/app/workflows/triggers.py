"""Workflow trigger adapters for document domain events."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, cast
from uuid import uuid4

from app.jobs.contracts import (
    DocumentProcessingCommand,
    JobPriority,
    JobRef,
    JobStatus,
)
from app.models.base import utc_now
from app.models.document import DocumentType
from app.models.jobs import (
    OutboxEvent,
    OutboxEventStatus,
    WorkflowJob,
    WorkflowJobStatus,
)
from app.services.bank_statement_import import BankStatementImportResult
from app.services.document_events import DocumentIngested, WorkflowJobSubmission
from app.services.workflow_outputs import (
    MaterializedInvoiceReview,
    WorkflowOutputPersistenceService,
)
from app.workflows.contracts import (
    WorkflowArtifactRef,
    WorkflowState,
)
from app.workflows.replay import (
    WORKFLOW_REPLAY_NAME,
    WORKFLOW_REPLAY_VERSION,
    ReplayScenario,
    WorkflowReplayResult,
    WorkflowReplayRunner,
)
from app.workflows.runtime import WorkflowRuntimePersistence, WorkflowRuntimeService

logger = logging.getLogger(__name__)


class BankStatementImporter(Protocol):
    """Imports bank statement document events into transaction rows."""

    async def import_document(
        self,
        event: DocumentIngested,
    ) -> BankStatementImportResult | None:
        """Import one bank statement document."""


class WorkflowSubmissionPersistence(WorkflowRuntimePersistence, Protocol):
    """Stage a workflow run, durable job, and outbox event in one transaction."""

    def add_workflow_job(self, job: WorkflowJob) -> WorkflowJob:
        """Stage one durable workflow job."""

    def add_outbox_event(self, event: OutboxEvent) -> OutboxEvent:
        """Stage one transactional outbox event."""


def workflow_state_from_document_ingested(event: DocumentIngested) -> WorkflowState:
    """Create initial workflow state from a document-ingested event."""

    artifact_metadata: dict[str, object] = {}
    if event.local_path is not None:
        artifact_metadata["local_path"] = event.local_path

    return WorkflowState(
        tenant_id=event.tenant_id,
        document_id=event.document_id,
        document_type=event.document_type,
        artifacts={
            "original": WorkflowArtifactRef(
                artifact_type="original",
                uri=event.storage_uri,
                media_type=None,
                content_hash=event.content_hash,
                metadata=artifact_metadata,
            )
        },
        policy_flags={
            "malware_scan_status": event.malware_scan_status,
            "source_event_id": str(event.event_id),
            "source_event_name": event.event_name,
            "correlation_id": event.correlation_id,
        },
    )


class DocumentIngestedWorkflowPublisher:
    """Local event publisher that triggers the document workflow immediately."""

    def __init__(
        self,
        *,
        runner: WorkflowReplayRunner,
        output_persistence_service: WorkflowOutputPersistenceService | None = None,
        bank_statement_importer: BankStatementImporter | None = None,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.runner = runner
        self.output_persistence_service = output_persistence_service
        self.bank_statement_importer = bank_statement_importer
        self.commit = commit
        self.last_result: WorkflowReplayResult | None = None
        self.last_materialized_invoice_review: MaterializedInvoiceReview | None = None
        self.last_bank_statement_import: BankStatementImportResult | None = None

    async def publish_document_ingested(
        self,
        event: DocumentIngested,
    ) -> WorkflowJobSubmission | None:
        """Trigger a local workflow run for an accepted document."""

        if event.document_type == DocumentType.BANK_STATEMENT.value:
            if self.bank_statement_importer is not None:
                self.last_bank_statement_import = (
                    await self.bank_statement_importer.import_document(event)
                )
            logger.info(
                "Imported bank statement document %s into %s transaction(s).",
                event.document_id,
                self.last_bank_statement_import.transaction_count
                if self.last_bank_statement_import is not None
                else 0,
            )
            if self.commit is not None:
                await self.commit()
            return None

        if event.document_type != DocumentType.INVOICE.value:
            logger.info(
                "Skipping invoice extraction workflow for document type %s.",
                event.document_type,
            )
            if self.commit is not None:
                await self.commit()
            return None

        state = workflow_state_from_document_ingested(event)
        correlation_id = event.correlation_id or f"document-ingested:{event.event_id}"
        self.last_result = await self.runner.run(
            state=state,
            scenario=ReplayScenario.HAPPY_PATH,
            correlation_id=correlation_id,
        )
        if self.output_persistence_service is not None:
            service = self.output_persistence_service
            materialized = await service.persist_invoice_review_from_workflow_result(
                self.last_result
            )
            self.last_materialized_invoice_review = materialized
        if self.commit is not None:
            await self.commit()
        return None


class QueuedDocumentWorkflowPublisher:
    """Stage durable document work for transactional outbox delivery."""

    def __init__(
        self,
        *,
        persistence: WorkflowSubmissionPersistence,
        max_attempts: int = 4,
    ) -> None:
        self.runtime = WorkflowRuntimeService(persistence)
        self.persistence = persistence
        self.max_attempts = max_attempts

    async def publish_document_ingested(
        self,
        event: DocumentIngested,
    ) -> WorkflowJobSubmission | None:
        """Stage a queued run, job, and outbox event without external I/O."""

        if event.document_type not in {
            DocumentType.INVOICE.value,
            DocumentType.BANK_STATEMENT.value,
        }:
            logger.info(
                "Skipping workflow queue for document type %s.",
                event.document_type,
            )
            return None

        state = workflow_state_from_document_ingested(event)
        correlation_id = event.correlation_id or f"document-ingested:{event.event_id}"
        workflow_run = self.runtime.queue_workflow(
            state=state,
            workflow_name=WORKFLOW_REPLAY_NAME,
            workflow_version=WORKFLOW_REPLAY_VERSION,
            correlation_id=correlation_id,
        )
        command = DocumentProcessingCommand(
            job_id=workflow_run.id,
            workflow_run_id=workflow_run.id,
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            document_id=event.document_id,
            document_type=event.document_type,
            storage_uri=event.storage_uri,
            content_hash=event.content_hash,
            malware_scan_status=event.malware_scan_status,
            local_path=event.local_path,
            correlation_id=correlation_id,
            priority=JobPriority.HIGH,
        )
        command_payload = cast(dict[str, object], command.model_dump(mode="json"))
        durable_job = WorkflowJob(
            id=workflow_run.id,
            tenant_id=event.tenant_id,
            workflow_run_id=workflow_run.id,
            document_id=event.document_id,
            idempotency_key=str(workflow_run.id),
            status=WorkflowJobStatus.QUEUED.value,
            priority=command.priority.value,
            command=command_payload,
            max_attempts=self.max_attempts,
            available_at=utc_now(),
        )
        self.persistence.add_workflow_job(durable_job)
        self.persistence.add_outbox_event(
            OutboxEvent(
                id=uuid4(),
                tenant_id=event.tenant_id,
                workflow_job_id=durable_job.id,
                aggregate_type="workflow_run",
                aggregate_id=workflow_run.id,
                event_type="DocumentProcessingRequested",
                payload={"command": command_payload},
                status=OutboxEventStatus.PENDING.value,
                available_at=utc_now(),
            )
        )
        job = JobRef(
            job_id=durable_job.id,
            workflow_run_id=workflow_run.id,
            status=JobStatus.QUEUED,
            priority=command.priority,
        )
        logger.info(
            "workflow.job.staged",
            extra={
                "event": "workflow.job.staged",
                "job_id": str(job.job_id),
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(event.tenant_id),
                "document_id": str(event.document_id),
                "correlation_id": correlation_id,
            },
        )
        return WorkflowJobSubmission(workflow_run_id=workflow_run.id, job=job)
