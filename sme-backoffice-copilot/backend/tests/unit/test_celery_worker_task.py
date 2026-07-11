from uuid import uuid4

from app.jobs import DocumentProcessingCommand
from app.workers import tasks


def build_command() -> DocumentProcessingCommand:
    return DocumentProcessingCommand(
        workflow_run_id=uuid4(),
        event_id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        content_hash="hash-123",
        malware_scan_status="not_scanned",
    )


def test_celery_task_loads_portable_command_without_live_broker(monkeypatch) -> None:
    command = build_command()
    executed: list[tuple[DocumentProcessingCommand, bool]] = []

    class FakeExecutor:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["progress_observer"] is not None

        async def execute(
            self,
            received_command: DocumentProcessingCommand,
            *,
            mark_failed: bool,
        ) -> None:
            executed.append((received_command, mark_failed))

    monkeypatch.setattr(tasks, "DocumentProcessingWorkflowExecutor", FakeExecutor)

    result = tasks.execute_document_processing.apply(
        args=[command.model_dump(mode="json")],
        throw=True,
    )

    assert result.result is None
    assert executed == [(command, False)]
