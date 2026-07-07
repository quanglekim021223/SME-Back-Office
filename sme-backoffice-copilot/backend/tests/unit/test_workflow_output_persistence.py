from uuid import UUID

from app.models.document import DocumentStatus
from app.models.invoice import Invoice, InvoiceFieldEvidence, InvoiceLineItem
from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.observability.tracing import InMemoryTraceProvider
from app.providers import (
    MockLLMProvider,
    MockOCRProvider,
    ProviderRuntime,
    build_default_provider_routing_config,
)
from app.providers.errors import ProviderDependencyError
from app.providers.ocr import OCRInput, OCRProviderRunContext, OCRResult
from app.services.workflow_outputs import (
    WorkflowOutputPersistenceService,
    get_assembled_invoice_draft,
)
from app.workflows.replay import WorkflowReplayRunner, create_replay_state


class FailingOCRProvider:
    @property
    def name(self) -> str:
        return "failing_ocr"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        del input_data, context
        raise ProviderDependencyError("OCR dependency is not installed.")


class FakeWorkflowOutputPersistence:
    def __init__(self) -> None:
        self.invoices: list[Invoice] = []
        self.line_items: list[InvoiceLineItem] = []
        self.field_evidence: list[InvoiceFieldEvidence] = []
        self.review_tasks: list[ReviewTask] = []
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

    async def mark_document_status(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        status: DocumentStatus,
    ) -> None:
        self.document_status_updates.append((tenant_id, document_id, status))


async def test_workflow_output_service_materializes_invoice_review_task() -> None:
    state = create_replay_state()
    result = await WorkflowReplayRunner(
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=MockLLMProvider(),
        ocr_provider=MockOCRProvider(),
    ).run(state=state)
    persistence = FakeWorkflowOutputPersistence()
    service = WorkflowOutputPersistenceService(persistence)

    materialized = await service.persist_invoice_review_from_workflow_result(result)

    assert materialized is not None
    assert materialized.invoice is persistence.invoices[0]
    assert materialized.review_task is persistence.review_tasks[0]
    assert materialized.invoice.tenant_id == state.tenant_id
    assert materialized.invoice.document_id == state.document_id
    assert materialized.invoice.invoice_number == "INV-MOCK-001"
    assert materialized.invoice.supplier_name == "Mock Supplier Ltd"
    assert str(materialized.invoice.total_amount) == "110.00"
    assert materialized.invoice.status == "pending_review"
    assert persistence.line_items[0].invoice_id == materialized.invoice.id
    assert persistence.line_items[0].description == "Mock consulting service"
    assert persistence.field_evidence
    assert materialized.review_task.invoice_id == materialized.invoice.id
    assert materialized.review_task.task_type == ReviewTaskType.EXTRACTION.value
    assert materialized.review_task.status == ReviewTaskStatus.OPEN.value
    assert materialized.review_task.evidence_refs == [
        "mock:page:1",
        "ocr:text:fallback:metadata",
        "mock:page:1:table:row:1",
        "mock:page:1:table",
        "ocr:text:fallback:table",
        "mock:page:1:totals",
        "ocr:text:fallback:totals",
    ]
    assert materialized.review_task.metadata_ is not None
    diagnostics = materialized.review_task.metadata_["ocr_layout_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["provider_name"] == "mock_ocr"
    assert diagnostics["text_block_count"] > 0
    assert persistence.document_status_updates == [
        (state.tenant_id, state.document_id, DocumentStatus.REVIEW_REQUIRED)
    ]


async def test_workflow_output_service_traces_review_task_creation() -> None:
    state = create_replay_state()
    result = await WorkflowReplayRunner(
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=MockLLMProvider(),
        ocr_provider=MockOCRProvider(),
    ).run(state=state)
    persistence = FakeWorkflowOutputPersistence()
    trace_provider = InMemoryTraceProvider()
    service = WorkflowOutputPersistenceService(
        persistence,
        trace_provider=trace_provider,
    )

    materialized = await service.persist_invoice_review_from_workflow_result(result)

    assert materialized is not None
    event = next(
        event
        for event in trace_provider.events
        if event.name == "review_task.created"
    )
    assert event.payload["source"] == "invoice_proposal"
    assert event.payload["task_type"] == ReviewTaskType.EXTRACTION.value
    assert event.payload["status"] == ReviewTaskStatus.OPEN.value
    assert event.payload["has_invoice_id"] is True


async def test_workflow_output_service_skips_when_invoice_draft_is_missing() -> None:
    state = create_replay_state()
    result = await WorkflowReplayRunner().run(state=state)
    result.state.scratchpad.clear()
    persistence = FakeWorkflowOutputPersistence()
    service = WorkflowOutputPersistenceService(persistence)

    materialized = await service.persist_invoice_review_from_workflow_result(result)

    assert get_assembled_invoice_draft(result) is None
    assert materialized is None
    assert persistence.invoices == []
    assert persistence.review_tasks == []


async def test_workflow_output_service_creates_review_task_when_workflow_fails() -> (
    None
):
    state = create_replay_state()
    result = await WorkflowReplayRunner(
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        ocr_provider=FailingOCRProvider(),
    ).run(state=state)
    persistence = FakeWorkflowOutputPersistence()
    service = WorkflowOutputPersistenceService(persistence)

    materialized = await service.persist_invoice_review_from_workflow_result(result)

    assert materialized is None
    assert persistence.invoices == []
    assert len(persistence.review_tasks) == 1
    review_task = persistence.review_tasks[0]
    assert review_task.document_id == state.document_id
    assert review_task.invoice_id is None
    assert review_task.task_type == ReviewTaskType.EXTRACTION.value
    assert review_task.target_type == ReviewTargetType.DOCUMENT.value
    assert review_task.reason_code == "ERR_OCR_PROVIDER_FAILED"
    assert review_task.metadata_ is not None
    assert review_task.metadata_["source"] == "workflow_failure"
    assert persistence.document_status_updates == [
        (state.tenant_id, state.document_id, DocumentStatus.REVIEW_REQUIRED)
    ]


async def test_output_service_creates_review_task_for_review_required() -> None:
    """Output service creates document review task for REVIEW_REQUIRED without draft.

    This is a defensive path: if a workflow ends with REVIEW_REQUIRED status but the
    assembled invoice draft is absent (e.g., early extractor termination), the document
    must not silently disappear from the review queue.
    """
    from app.workflows.contracts import WorkflowStateStatus

    state = create_replay_state()
    # Run workflow normally without providers so it completes successfully.
    result = await WorkflowReplayRunner().run(state=state)
    # Simulate REVIEW_REQUIRED termination before assembly by clearing the draft and
    # forcing the status.
    result.state.scratchpad.pop("assembled_invoice_draft", None)
    result.state.status = WorkflowStateStatus.REVIEW_REQUIRED

    persistence = FakeWorkflowOutputPersistence()
    service = WorkflowOutputPersistenceService(persistence)

    materialized = await service.persist_invoice_review_from_workflow_result(result)

    assert materialized is None
    assert persistence.invoices == []
    assert len(persistence.review_tasks) == 1
    review_task = persistence.review_tasks[0]
    assert review_task.document_id == state.document_id
    assert review_task.invoice_id is None
    assert review_task.task_type == ReviewTaskType.EXTRACTION.value
    assert review_task.target_type == ReviewTargetType.DOCUMENT.value
    assert persistence.document_status_updates == [
        (state.tenant_id, state.document_id, DocumentStatus.REVIEW_REQUIRED)
    ]
