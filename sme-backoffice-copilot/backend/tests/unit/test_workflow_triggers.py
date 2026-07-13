from uuid import uuid4

from app.jobs import JobStatus
from app.models.jobs import OutboxEvent, WorkflowJob
from app.models.workflow import (
    AgentHandoff,
    AgentStepExecution,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.providers import (
    MockLLMProvider,
    MockOCRProvider,
    ProviderRuntime,
    build_default_provider_routing_config,
)
from app.services.bank_statement_import import BankStatementImportResult
from app.services.document_events import DocumentIngested
from app.workflows import OCR_FULL_TEXT_KEY, OCR_RESULT_KEY, WorkflowStateStatus
from app.workflows.replay import WorkflowReplayRunner
from app.workflows.triggers import (
    DocumentIngestedWorkflowPublisher,
    QueuedDocumentWorkflowPublisher,
    workflow_state_from_document_ingested,
)


class FakeQueuedWorkflowPersistence:
    def __init__(self) -> None:
        self.workflow_runs: list[WorkflowRun] = []
        self.step_executions: list[AgentStepExecution] = []
        self.handoffs: list[AgentHandoff] = []
        self.workflow_jobs: list[WorkflowJob] = []
        self.outbox_events: list[OutboxEvent] = []
        self.commit_calls = 0

    def add_workflow_run(self, workflow_run: WorkflowRun) -> WorkflowRun:
        self.workflow_runs.append(workflow_run)
        return workflow_run

    def add_step_execution(
        self,
        step_execution: AgentStepExecution,
    ) -> AgentStepExecution:
        self.step_executions.append(step_execution)
        return step_execution

    def add_handoff(self, handoff: AgentHandoff) -> AgentHandoff:
        self.handoffs.append(handoff)
        return handoff

    def add_workflow_job(self, job: WorkflowJob) -> WorkflowJob:
        self.workflow_jobs.append(job)
        return job

    def add_outbox_event(self, event: OutboxEvent) -> OutboxEvent:
        self.outbox_events.append(event)
        return event

    async def commit(self) -> None:
        self.commit_calls += 1


def create_document_ingested_event() -> DocumentIngested:
    return DocumentIngested(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        content_hash="hash-123",
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        malware_scan_status="not_scanned",
        local_path="/tmp/invoice.pdf",
    )


def test_workflow_state_from_document_ingested_event_preserves_artifact_context() -> (
    None
):
    event = create_document_ingested_event()

    state = workflow_state_from_document_ingested(event)

    assert state.tenant_id == event.tenant_id
    assert state.document_id == event.document_id
    assert state.document_type == "invoice"
    assert state.policy_flags["malware_scan_status"] == "not_scanned"
    assert state.policy_flags["source_event_id"] == str(event.event_id)
    assert state.policy_flags["correlation_id"] is None
    assert state.artifacts["original"].uri == event.storage_uri
    assert state.artifacts["original"].content_hash == event.content_hash
    assert state.artifacts["original"].metadata["local_path"] == "/tmp/invoice.pdf"


async def test_document_ingested_publisher_triggers_local_workflow() -> None:
    event = create_document_ingested_event()
    commit_calls = 0

    async def fake_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1

    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=MockLLMProvider(),
            ocr_provider=MockOCRProvider(),
        ),
        commit=fake_commit,
    )

    await publisher.publish_document_ingested(event)

    assert publisher.last_result is not None
    assert publisher.last_result.state.status == WorkflowStateStatus.COMPLETED
    assert publisher.last_result.state.document_id == event.document_id
    assert publisher.last_result.workflow_run.correlation_id == (
        f"document-ingested:{event.event_id}"
    )
    assert OCR_RESULT_KEY in publisher.last_result.state.scratchpad
    assert OCR_FULL_TEXT_KEY in publisher.last_result.state.scratchpad
    assert commit_calls == 1


async def test_document_ingested_publisher_uses_event_correlation_id() -> None:
    event = DocumentIngested(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        content_hash="hash-123",
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        malware_scan_status="not_scanned",
        local_path="/tmp/invoice.pdf",
        correlation_id="request-corr-123",
    )
    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=MockLLMProvider(),
            ocr_provider=MockOCRProvider(),
        ),
    )

    await publisher.publish_document_ingested(event)

    assert publisher.last_result is not None
    assert publisher.last_result.workflow_run.correlation_id == "request-corr-123"


async def test_document_ingested_publisher_skips_non_invoice_documents() -> None:
    event = DocumentIngested(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="bank_statement",
        content_hash="hash-123",
        storage_uri="local://tenants/t/documents/d/original/statement.csv",
        malware_scan_status="not_scanned",
        local_path="/tmp/statement.csv",
    )
    commit_calls = 0

    async def fake_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1

    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=MockLLMProvider(),
            ocr_provider=MockOCRProvider(),
        ),
        commit=fake_commit,
    )

    await publisher.publish_document_ingested(event)

    assert publisher.last_result is None
    assert publisher.last_materialized_invoice_review is None
    assert commit_calls == 1


async def test_document_ingested_publisher_imports_bank_statement_documents() -> None:
    event = DocumentIngested(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="bank_statement",
        content_hash="hash-123",
        storage_uri="local://tenants/t/documents/d/original/statement.csv",
        malware_scan_status="not_scanned",
        local_path="/tmp/statement.csv",
    )
    commit_calls = 0

    class FakeBankStatementImporter:
        calls = 0

        async def import_document(
            self,
            event: DocumentIngested,
        ) -> BankStatementImportResult:
            self.calls += 1
            return BankStatementImportResult(
                statement_import_id=uuid4(),
                transaction_count=4,
                reconciliation_count=1,
                review_task_count=0,
            )

    importer = FakeBankStatementImporter()

    async def fake_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1

    publisher = DocumentIngestedWorkflowPublisher(
        runner=WorkflowReplayRunner(
            provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
            llm_provider=MockLLMProvider(),
            ocr_provider=MockOCRProvider(),
        ),
        bank_statement_importer=importer,
        commit=fake_commit,
    )

    await publisher.publish_document_ingested(event)

    assert publisher.last_result is None
    assert importer.calls == 1
    assert publisher.last_bank_statement_import is not None
    assert publisher.last_bank_statement_import.transaction_count == 4
    assert commit_calls == 1


async def test_queued_document_publisher_stages_job_and_outbox_atomically() -> None:
    event = create_document_ingested_event()
    persistence = FakeQueuedWorkflowPersistence()
    publisher = QueuedDocumentWorkflowPublisher(persistence=persistence)

    submission = await publisher.publish_document_ingested(event)

    assert submission is not None
    assert persistence.commit_calls == 0
    assert len(persistence.workflow_runs) == 1
    workflow_run = persistence.workflow_runs[0]
    assert workflow_run.id == submission.workflow_run_id
    assert workflow_run.status == WorkflowRunStatus.QUEUED.value
    assert workflow_run.state is not None
    assert workflow_run.state["status"] == "queued"
    assert submission.job.status is JobStatus.QUEUED
    assert submission.job.job_id == workflow_run.id
    assert len(persistence.workflow_jobs) == 1
    durable_job = persistence.workflow_jobs[0]
    assert durable_job.workflow_run_id == workflow_run.id
    assert durable_job.idempotency_key == str(workflow_run.id)
    assert durable_job.command["event_id"] == str(event.event_id)
    assert len(persistence.outbox_events) == 1
    assert persistence.outbox_events[0].workflow_job_id == durable_job.id
    assert persistence.outbox_events[0].payload["command"] == durable_job.command
