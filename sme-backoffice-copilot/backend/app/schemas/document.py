"""Document API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MalwareScanResponse(BaseModel):
    """Malware scan summary returned after upload."""

    status: str
    scanner_name: str
    scanner_version: str | None = None
    scanned_at: datetime | None = None
    signature_version: str | None = None
    threats: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)


class DocumentWorkflowTriggerResponse(BaseModel):
    """Workflow trigger summary returned after upload."""

    event_id: UUID
    event_name: str
    document_id: UUID
    status: str = "published"


class DocumentUploadResponse(BaseModel):
    """Response returned after a document upload is accepted."""

    id: UUID
    tenant_id: UUID
    document_type: str
    status: str
    original_filename: str
    mime_type: str
    size_bytes: int
    content_hash: str
    storage_uri: str
    malware_scan: MalwareScanResponse
    workflow_trigger: DocumentWorkflowTriggerResponse
    duplicate: bool = Field(default=False)
