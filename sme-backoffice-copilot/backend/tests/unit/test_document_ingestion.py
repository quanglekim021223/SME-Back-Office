import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.accounting import (
    ClassificationProposal,
    Reconciliation,
    ReconciliationAllocation,
)
from app.models.document import (
    ArtifactType,
    Document,
    DocumentArtifact,
    DocumentStatus,
    DocumentType,
)
from app.models.invoice import Invoice, InvoiceFieldEvidence, InvoiceLineItem
from app.models.operations import ReviewTask, ReviewTaskStatus, ReviewTaskType
from app.providers import (
    MockLLMProvider,
    MockOCRProvider,
    OllamaLLMProvider,
    ProviderDeploymentMode,
    ProviderRuntime,
    build_default_provider_routing_config,
)
from app.services.document_events import DocumentEventPublisher, DocumentIngested
from app.services.document_ingestion import (
    DocumentIngestionService,
    DuplicateDocumentError,
)
from app.services.document_storage import (
    FileValidationError,
    LocalDocumentStorage,
    compute_content_hash,
)
from app.services.malware_scan import MalwareScanStatus
from app.services.workflow_outputs import WorkflowOutputPersistenceService
from app.workflows.replay import WorkflowReplayRunner
from app.workflows.triggers import DocumentIngestedWorkflowPublisher


class FakeDocumentPersistence:
    def __init__(self, existing_document: Document | None = None) -> None:
        self.existing_document = existing_document
        self.documents: list[Document] = []
        self.artifacts: list[DocumentArtifact] = []
        self.committed = False

    async def get_by_tenant_and_content_hash(
        self,
        *,
        tenant_id: UUID,
        content_hash: str,
    ) -> Document | None:
        del tenant_id, content_hash
        return self.existing_document

    def add_document(self, document: Document) -> Document:
        self.documents.append(document)
        return document

    def add_artifact(self, artifact: DocumentArtifact) -> DocumentArtifact:
        self.artifacts.append(artifact)
        return artifact

    async def commit(self) -> None:
        self.committed = True


class FakeDocumentEventPublisher:
    def __init__(self) -> None:
        self.events: list[DocumentIngested] = []

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
        self.events.append(event)


class FakeWorkflowOutputPersistence:
    def __init__(self) -> None:
        self.invoices: list[Invoice] = []
        self.line_items: list[InvoiceLineItem] = []
        self.field_evidence: list[InvoiceFieldEvidence] = []
        self.review_tasks: list[ReviewTask] = []
        self.classification_proposals: list[ClassificationProposal] = []
        self.reconciliations: list[Reconciliation] = []
        self.reconciliation_allocations: list[ReconciliationAllocation] = []
        self.document_status_updates: list[tuple[UUID, UUID, DocumentStatus]] = []

    def add_invoice(self, invoice: Invoice) -> Invoice:
        self.invoices.append(invoice)
        return invoice

    def add_invoice_line_item(self, line_item: InvoiceLineItem) -> InvoiceLineItem:
        self.line_items.append(line_item)
        return line_item

    def add_invoice_field_evidence(
        self,
        field_evidence: InvoiceFieldEvidence,
    ) -> InvoiceFieldEvidence:
        self.field_evidence.append(field_evidence)
        return field_evidence

    def add_review_task(self, review_task: ReviewTask) -> ReviewTask:
        self.review_tasks.append(review_task)
        return review_task

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        self.classification_proposals.append(proposal)
        return proposal

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        self.reconciliations.append(reconciliation)
        return reconciliation

    def add_reconciliation_allocation(
        self,
        allocation: ReconciliationAllocation,
    ) -> ReconciliationAllocation:
        self.reconciliation_allocations.append(allocation)
        return allocation

    async def mark_document_status(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        status: DocumentStatus,
    ) -> None:
        self.document_status_updates.append((tenant_id, document_id, status))


def create_service(
    *,
    root_path: Path,
    persistence: FakeDocumentPersistence,
    allowed_mime_types: set[str] | None = None,
    event_publisher: DocumentEventPublisher | None = None,
) -> DocumentIngestionService:
    storage = LocalDocumentStorage(
        root_path=root_path,
        max_size_bytes=1024,
        allowed_mime_types=allowed_mime_types or {"application/pdf"},
    )
    return DocumentIngestionService(
        persistence=persistence,
        storage=storage,
        event_publisher=event_publisher,
    )


@pytest.mark.asyncio
async def test_document_ingestion_stores_file_and_creates_accepted_document(
    tmp_path: Path,
) -> None:
    persistence = FakeDocumentPersistence()
    event_publisher = FakeDocumentEventPublisher()
    service = create_service(
        root_path=tmp_path,
        persistence=persistence,
        event_publisher=event_publisher,
    )
    tenant_id = uuid4()
    content = b"%PDF-1.4 sample"

    result = await service.upload_document(
        tenant_id=tenant_id,
        filename="invoice.pdf",
        content=content,
        media_type="application/pdf",
        document_type=DocumentType.INVOICE,
        correlation_id="corr-upload-123",
    )

    assert result.stored_file.path.read_bytes() == content
    assert result.document in persistence.documents
    assert result.document.tenant_id == tenant_id
    assert result.document.document_type == DocumentType.INVOICE.value
    assert result.document.status == DocumentStatus.ACCEPTED.value
    assert result.document.content_hash == compute_content_hash(content)
    assert result.artifact in persistence.artifacts
    assert result.artifact.document_id == result.document.id
    assert result.artifact.artifact_type == ArtifactType.ORIGINAL.value
    assert result.artifact.storage_uri.startswith("local://")
    assert result.malware_scan_result.status == MalwareScanStatus.NOT_SCANNED
    assert result.artifact.metadata_ is not None
    malware_scan_metadata = result.artifact.metadata_["malware_scan"]
    assert isinstance(malware_scan_metadata, dict)
    assert malware_scan_metadata["status"] == MalwareScanStatus.NOT_SCANNED.value
    assert persistence.committed is True
    assert event_publisher.events == [result.document_ingested_event]
    assert result.document_ingested_event.event_name == "DocumentIngested"
    assert result.document_ingested_event.tenant_id == tenant_id
    assert result.document_ingested_event.document_id == result.document.id
    assert result.document_ingested_event.storage_uri == result.artifact.storage_uri
    assert result.document_ingested_event.local_path == str(result.stored_file.path)
    assert result.document_ingested_event.correlation_id == "corr-upload-123"


@pytest.mark.asyncio
async def test_local_upload_to_review_smoke_test_with_mock_providers(
    tmp_path: Path,
) -> None:
    document_persistence = FakeDocumentPersistence()
    workflow_persistence = FakeWorkflowOutputPersistence()
    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=MockLLMProvider(),
            ocr_provider=MockOCRProvider(),
        ),
        output_persistence_service=WorkflowOutputPersistenceService(
            workflow_persistence,
        ),
    )
    service = create_service(
        root_path=tmp_path,
        persistence=document_persistence,
        event_publisher=publisher,
    )

    result = await service.upload_document(
        tenant_id=uuid4(),
        filename="invoice.pdf",
        content=b"%PDF-1.4 local smoke test invoice",
        media_type="application/pdf",
        document_type=DocumentType.INVOICE,
    )

    assert result.document.status == DocumentStatus.ACCEPTED.value
    assert publisher.last_result is not None
    assert publisher.last_materialized_invoice_review is not None
    assert len(workflow_persistence.invoices) == 1
    assert workflow_persistence.invoices[0].invoice_number == "INV-MOCK-001"
    assert workflow_persistence.line_items[0].description == "Mock consulting service"
    assert len(workflow_persistence.review_tasks) == 1
    review_task = workflow_persistence.review_tasks[0]
    assert review_task.document_id == result.document.id
    assert review_task.invoice_id == workflow_persistence.invoices[0].id
    assert review_task.task_type == ReviewTaskType.EXTRACTION.value
    assert review_task.status == ReviewTaskStatus.OPEN.value
    assert workflow_persistence.document_status_updates[0][2] == (
        DocumentStatus.REVIEW_REQUIRED
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_SMOKE_TEST") != "1",
    reason="Requires local Ollama server and model.",
)
async def test_local_upload_to_review_smoke_test_with_ollama_provider(
    tmp_path: Path,
) -> None:
    document_persistence = FakeDocumentPersistence()
    workflow_persistence = FakeWorkflowOutputPersistence()
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(
                build_default_provider_routing_config(
                    llm_provider_name="ollama",
                    llm_model_name=ollama_model,
                    llm_deployment_mode=ProviderDeploymentMode.LOCAL,
                    timeout_seconds=90.0,
                    max_retries=0,
                )
            ),
            llm_provider=OllamaLLMProvider(
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                model_name=ollama_model,
                timeout_seconds=90.0,
            ),
            ocr_provider=MockOCRProvider(),
        ),
        output_persistence_service=WorkflowOutputPersistenceService(
            workflow_persistence,
        ),
    )
    service = create_service(
        root_path=tmp_path,
        persistence=document_persistence,
        event_publisher=publisher,
    )

    result = await service.upload_document(
        tenant_id=uuid4(),
        filename="invoice.pdf",
        content=b"%PDF-1.4 ollama smoke test invoice",
        media_type="application/pdf",
        document_type=DocumentType.INVOICE,
    )

    assert result.document.status == DocumentStatus.ACCEPTED.value
    assert publisher.last_result is not None
    assert len(workflow_persistence.review_tasks) == 1
    assert workflow_persistence.review_tasks[0].status == ReviewTaskStatus.OPEN.value
    assert workflow_persistence.document_status_updates[0][2] == (
        DocumentStatus.REVIEW_REQUIRED
    )


@pytest.mark.asyncio
async def test_local_upload_to_review_falls_back_when_provider_output_is_invalid(
    tmp_path: Path,
) -> None:
    document_persistence = FakeDocumentPersistence()
    workflow_persistence = FakeWorkflowOutputPersistence()
    invalid_llm = MockLLMProvider(
        structured_outputs={
            "invoice-metadata-group.v1": {"unexpected": "shape"},
            "invoice-table-group.v1": {"unexpected": "shape"},
            "invoice-totals-group.v1": {"unexpected": "shape"},
        }
    )
    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=invalid_llm,
            ocr_provider=MockOCRProvider(),
        ),
        output_persistence_service=WorkflowOutputPersistenceService(
            workflow_persistence,
        ),
    )
    service = create_service(
        root_path=tmp_path,
        persistence=document_persistence,
        event_publisher=publisher,
    )

    result = await service.upload_document(
        tenant_id=uuid4(),
        filename="invoice.pdf",
        content=b"%PDF-1.4 invalid provider output smoke test",
        media_type="application/pdf",
        document_type=DocumentType.INVOICE,
    )

    assert result.document.status == DocumentStatus.ACCEPTED.value
    assert publisher.last_materialized_invoice_review is not None
    assert len(workflow_persistence.invoices) == 1
    assert len(workflow_persistence.review_tasks) == 1
    review_task = workflow_persistence.review_tasks[0]
    assert review_task.status == ReviewTaskStatus.OPEN.value
    assert review_task.metadata_ is not None
    assert review_task.metadata_["provider_extraction_errors"] != []
    assert workflow_persistence.document_status_updates[0][2] == (
        DocumentStatus.REVIEW_REQUIRED
    )


@pytest.mark.asyncio
async def test_document_ingestion_rejects_duplicate_before_storing_file(
    tmp_path: Path,
) -> None:
    existing_document = Document(
        id=uuid4(),
        tenant_id=uuid4(),
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.ACCEPTED.value,
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        content_hash="existing-hash",
    )
    persistence = FakeDocumentPersistence(existing_document=existing_document)
    event_publisher = FakeDocumentEventPublisher()
    service = create_service(
        root_path=tmp_path,
        persistence=persistence,
        event_publisher=event_publisher,
    )

    with pytest.raises(DuplicateDocumentError) as exc_info:
        await service.upload_document(
            tenant_id=uuid4(),
            filename="invoice.pdf",
            content=b"%PDF duplicate",
            media_type="application/pdf",
            document_type=DocumentType.INVOICE,
        )

    assert exc_info.value.existing_document is existing_document
    assert persistence.documents == []
    assert persistence.artifacts == []
    assert persistence.committed is False
    assert list(tmp_path.rglob("*")) == []  # noqa: ASYNC240
    assert event_publisher.events == []


@pytest.mark.asyncio
async def test_document_ingestion_rejects_unsupported_mime_type(
    tmp_path: Path,
) -> None:
    persistence = FakeDocumentPersistence()
    service = create_service(root_path=tmp_path, persistence=persistence)

    with pytest.raises(FileValidationError) as exc_info:
        await service.upload_document(
            tenant_id=uuid4(),
            filename="script.sh",
            content=b"echo unsafe",
            media_type="text/x-shellscript",
            document_type=DocumentType.OTHER,
        )

    assert exc_info.value.code == "UNSUPPORTED_MIME_TYPE"
    assert persistence.documents == []
    assert persistence.artifacts == []
