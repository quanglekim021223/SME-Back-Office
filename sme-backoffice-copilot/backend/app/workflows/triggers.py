"""Workflow trigger adapters for document domain events."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.models.document import DocumentType
from app.services.bank_statement_import import BankStatementImportResult
from app.services.document_events import DocumentIngested
from app.services.workflow_outputs import (
    MaterializedInvoiceReview,
    WorkflowOutputPersistenceService,
)
from app.workflows.contracts import (
    WorkflowArtifactRef,
    WorkflowState,
)
from app.workflows.replay import (
    ReplayScenario,
    WorkflowReplayResult,
    WorkflowReplayRunner,
)

logger = logging.getLogger(__name__)


class BankStatementImporter(Protocol):
    """Imports bank statement document events into transaction rows."""

    async def import_document(
        self,
        event: DocumentIngested,
    ) -> BankStatementImportResult | None:
        """Import one bank statement document."""


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

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
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
            return

        if event.document_type != DocumentType.INVOICE.value:
            logger.info(
                "Skipping invoice extraction workflow for document type %s.",
                event.document_type,
            )
            if self.commit is not None:
                await self.commit()
            return

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
