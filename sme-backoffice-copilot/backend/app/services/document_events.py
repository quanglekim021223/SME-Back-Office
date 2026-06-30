"""Document domain events and workflow trigger placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class DocumentIngested:
    """Event emitted after a document has been accepted and persisted."""

    tenant_id: UUID
    document_id: UUID
    document_type: str
    content_hash: str
    storage_uri: str
    malware_scan_status: str
    event_id: UUID = field(default_factory=uuid4)
    event_name: str = "DocumentIngested"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-compatible payload for future queue/outbox publishing."""

        return {
            "event_id": str(self.event_id),
            "event_name": self.event_name,
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": str(self.tenant_id),
            "document_id": str(self.document_id),
            "document_type": self.document_type,
            "content_hash": self.content_hash,
            "storage_uri": self.storage_uri,
            "malware_scan_status": self.malware_scan_status,
        }


class DocumentEventPublisher(Protocol):
    """Boundary for future workflow/event publishing infrastructure."""

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
        """Publish a document-ingested event or trigger a workflow."""


class NoopDocumentEventPublisher:
    """No-op publisher used until queue/outbox infrastructure is introduced."""

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
        """Acknowledge the trigger without sending it to external infrastructure."""

        del event
