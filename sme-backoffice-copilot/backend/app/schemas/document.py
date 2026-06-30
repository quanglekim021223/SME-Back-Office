"""Document API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


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
    duplicate: bool = Field(default=False)
