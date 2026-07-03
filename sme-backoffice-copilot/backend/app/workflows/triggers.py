"""Workflow trigger adapters for document domain events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.services.document_events import DocumentIngested
from app.workflows.contracts import (
    WorkflowArtifactRef,
    WorkflowState,
)
from app.workflows.replay import (
    ReplayScenario,
    WorkflowReplayResult,
    WorkflowReplayRunner,
)


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
        },
    )


class DocumentIngestedWorkflowPublisher:
    """Local event publisher that triggers the document workflow immediately."""

    def __init__(
        self,
        *,
        runner: WorkflowReplayRunner,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.runner = runner
        self.commit = commit
        self.last_result: WorkflowReplayResult | None = None

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
        """Trigger a local workflow run for an accepted document."""

        state = workflow_state_from_document_ingested(event)
        self.last_result = await self.runner.run(
            state=state,
            scenario=ReplayScenario.HAPPY_PATH,
            correlation_id=f"document-ingested:{event.event_id}",
        )
        if self.commit is not None:
            await self.commit()
